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
