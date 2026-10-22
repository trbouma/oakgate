import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from cryptography.fernet import Fernet


def pos_enabled():
    value = os.getenv('OAKGATE_POS_ENABLED', 'false').strip().lower()
    if value not in {'true', 'false'}:
        raise ValueError('OAKGATE_POS_ENABLED must be true or false')
    return value == 'true'


def origin(value, name, https=False):
    parsed = urlsplit(value)
    if (parsed.scheme not in ({'https'} if https else {'http', 'https'})
        or not parsed.hostname or parsed.username is not None or parsed.password is not None
        or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError(f'{name} must be a valid origin without credentials or a path')
    _ = parsed.port
    return value.rstrip('/')


@dataclass(frozen=True)
class POSSettings:
    enabled: bool
    public_url: str
    api_url: str
    cookie_key: str = field(repr=False)

    @classmethod
    def from_env(cls):
        enabled = pos_enabled()
        public = origin(os.getenv('OAKGATE_POS_PUBLIC_URL', 'https://pos.oakgate.safebox.dev'), 'OAKGATE_POS_PUBLIC_URL', https=enabled)
        api = origin(os.getenv('OAKGATE_POS_API_URL', 'http://app:8000'), 'OAKGATE_POS_API_URL')
        key = os.getenv('OAKGATE_POS_COOKIE_KEY', '')
        if enabled:
            try:
                Fernet(key.encode('ascii'))
            except (ValueError, UnicodeError):
                raise ValueError('Set OAKGATE_POS_COOKIE_KEY to a separate generated Fernet key before enabling POS') from None
        return cls(enabled, public, api, key)
