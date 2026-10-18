import pytest

from app.config import public_url


def test_local_origin_is_independent_of_keycloak(monkeypatch):
    monkeypatch.delenv("OAKGATE_PUBLIC_URL", raising=False)
    monkeypatch.setenv("KC_HOSTNAME", "https://keycloak.example.com")
    assert public_url() == "http://127.0.0.1:8801"


def test_public_origin_override(monkeypatch):
    monkeypatch.setenv("OAKGATE_PUBLIC_URL", "https://oakgate.safebox.dev/")
    assert public_url() == "https://oakgate.safebox.dev"


@pytest.mark.parametrize("value", ["oakgate.safebox.dev", "https://example.com/admin", "https://user:secret@example.com", "https://example.com:99999", "https://example.com?secret=x"])
def test_invalid_public_origin_is_rejected(monkeypatch, value):
    monkeypatch.setenv("OAKGATE_PUBLIC_URL", value)
    with pytest.raises(ValueError):
        public_url()


def test_session_lifetime_default_and_override(monkeypatch):
    from app.config import AuthSettings
    monkeypatch.delenv('OAKGATE_SESSION_TTL_SECONDS', raising=False)
    assert AuthSettings.from_env().session_ttl_seconds == 604800
    monkeypatch.setenv('OAKGATE_SESSION_TTL_SECONDS', '3600')
    assert AuthSettings.from_env().session_ttl_seconds == 3600


@pytest.mark.parametrize('value', ['0', '-1', 'abc', '1.5', '31536001'])
def test_invalid_session_lifetime(monkeypatch, value):
    from app.config import AuthSettings
    monkeypatch.setenv('OAKGATE_SESSION_TTL_SECONDS', value)
    with pytest.raises(ValueError):
        AuthSettings.from_env()
