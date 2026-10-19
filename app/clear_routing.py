"""Advisory Clear route scopes, matching Safebox Web's send guard.

This classifies routes, not issuers or mint acceptance. It is not a DNS or
recipient-reachability test; Acorn remains responsible for protocol execution.
"""
from ipaddress import ip_address
from urllib.parse import urlsplit


class ClearRouteError(ValueError):
    """Safe, user-facing refusal before any transfer starts."""


def clear_availability(mint):
    normalized = str(mint or '').strip().rstrip('/')
    try:
        parsed = urlsplit(normalized)
        hostname = str(parsed.hostname or '').lower().rstrip('.')
        port = parsed.port
    except ValueError:
        return 'instance'
    if (parsed.scheme.lower() not in {'http', 'https'} or not hostname
            or parsed.username is not None or parsed.password is not None
            or (port is not None and not 1 <= port <= 65535)
            or parsed.query or parsed.fragment):
        return 'instance'
    if hostname == 'localhost' or hostname.endswith('.localhost'):
        return 'instance'
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback:
            return 'instance'
        if address.is_private or address.is_link_local:
            return 'local'
    elif '.' not in hostname:
        return 'instance'
    if hostname.endswith(('.local', '.lan', '.internal', '.home.arpa')):
        return 'local'
    return 'across-networks' if parsed.scheme.lower() == 'https' else 'instance'
