import time
from urllib.parse import urlsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError
from authlib.oidc.core import CodeIDToken


class KeycloakProvider:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport
        self.cached_metadata = None
        self.metadata_until = 0
        self.cached_keys = None
        self.keys_until = 0

    async def read_json(self, url):
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def metadata(self):
        if self.cached_metadata and self.metadata_until > time.time():
            return self.cached_metadata
        issuer = self.settings.issuer
        data = await self.read_json(issuer + "/.well-known/openid-configuration")
        if data.get("issuer") != issuer:
            raise ValueError("Discovery issuer mismatch")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri", "end_session_endpoint"):
            endpoint = urlsplit(data[name])
            origin = urlsplit(issuer)
            if (endpoint.scheme, endpoint.netloc) != (origin.scheme, origin.netloc):
                raise ValueError("Unexpected Keycloak endpoint origin")
        self.cached_metadata = data
        self.metadata_until = time.time() + 300
        return data

    def client(self):
        return AsyncOAuth2Client(
            self.settings.client_id, self.settings.client_secret,
            scope="openid profile email", redirect_uri=self.settings.origin + "/auth/callback",
            code_challenge_method="S256", token_endpoint_auth_method="client_secret_basic",
            timeout=10, transport=self.transport,
        )

    async def authorize(self, transaction):
        metadata = await self.metadata()
        async with self.client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"], state=transaction["state"],
                nonce=transaction["nonce"], code_verifier=transaction["verifier"],
                **({'prompt': 'login', 'max_age': 0} if transaction.get('purpose') in {'recovery', 'nfc-enroll', 'nfc-login'} else {}),
            )
            return url

    async def keys(self, force=False):
        if force or not self.cached_keys or self.keys_until <= time.time():
            metadata = await self.metadata()
            self.cached_keys = await self.read_json(metadata["jwks_uri"])
            self.keys_until = time.time() + 300
        return self.cached_keys

    async def exchange(self, code, transaction):
        metadata = await self.metadata()
        async with self.client() as client:
            token = await client.fetch_token(
                metadata["token_endpoint"], code=code,
                code_verifier=transaction["verifier"], grant_type="authorization_code",
            )
        # Allow only the explicitly configured Keycloak signing algorithm.
        jwt = JsonWebToken(["RS256"])
        for attempt in range(2):
            try:
                claims = jwt.decode(
                    token["id_token"], await self.keys(force=bool(attempt)),
                    claims_cls=CodeIDToken,
                    claims_options={
                        "iss": {"essential": True, "value": self.settings.issuer},
                        "aud": {"essential": True, "value": self.settings.client_id},
                        "sub": {"essential": True},
                    },
                    claims_params={"nonce": transaction["nonce"],
                                   "client_id": self.settings.client_id,
                                   "access_token": token.get("access_token")},
                )
                break
            except (JoseError, ValueError):
                if attempt:
                    raise
        claims.validate(leeway=30)
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError("Missing subject")
        return dict(claims)
