import os
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
