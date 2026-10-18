import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def public_url() -> str:
    """Read the canonical origin; local development defaults to its own server."""
    value = os.getenv("OAKGATE_PUBLIC_URL", "http://127.0.0.1:8801").strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OAKGATE_PUBLIC_URL must be an HTTP(S) origin without credentials or a path")
    # Accessing port validates malformed and out-of-range port values.
    _ = parsed.port
    return value.rstrip("/")


@dataclass(frozen=True)
class AuthSettings:
    origin: str
    issuer: str = "https://keycloak.safebox.dev/realms/oakgate"
    client_id: str = "oakgate-web"
    client_secret: str = field(default="", repr=False)
    redis_url: str = field(default="", repr=False)

    session_ttl_seconds: int = 604800

    def __post_init__(self):
        if type(self.session_ttl_seconds) is not int or not 1 <= self.session_ttl_seconds <= 31536000:
            raise ValueError("OAKGATE_SESSION_TTL_SECONDS must be between 1 and 31536000 seconds")

    @property
    def secure(self):
        return self.origin.startswith("https://")

    @property
    def enabled(self):
        return bool(self.client_secret and not self.client_secret.startswith("<"))

    @classmethod
    def from_env(cls):
        settings = cls(
            origin=public_url(),
            session_ttl_seconds=int(os.getenv("OAKGATE_SESSION_TTL_SECONDS", "604800")),
            issuer=os.getenv("OAKGATE_OIDC_ISSUER", "https://keycloak.safebox.dev/realms/oakgate").rstrip("/"),
            client_id=os.getenv("OAKGATE_OIDC_CLIENT_ID", "oakgate-web"),
            client_secret=os.getenv("OAKGATE_OIDC_CLIENT_SECRET", ""),
            redis_url=os.getenv("OAKGATE_REDIS_URL", ""),
        )
        issuer = urlsplit(settings.issuer)
        if issuer.scheme != "https" or not issuer.hostname or issuer.username or issuer.password or issuer.query or issuer.fragment:
            raise ValueError("OAKGATE_OIDC_ISSUER must be a trusted HTTPS realm URL")
        if settings.enabled and not settings.secure and urlsplit(settings.origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP sign-in is allowed only for loopback development")
        if settings.enabled and settings.secure and not settings.redis_url:
            raise ValueError("HTTPS sign-in requires OAKGATE_REDIS_URL for server-side sessions")
        return settings
