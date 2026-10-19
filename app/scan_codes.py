"""Public code decoding adapted from Safebox Web; no network or key use."""
from urllib.parse import urlsplit, unquote
from bech32 import bech32_decode, convertbits

def decode_lnurl(value: str) -> str:
    """Decode a Bech32 LNURL into its absolute HTTP(S) URL."""

    normalized = str(value or "").strip()
    if normalized[:10].lower() == "lightning:":
        normalized = normalized[10:].strip()
    if not normalized.lower().startswith("lnurl1") or len(normalized) > 4096:
        raise ValueError("Value is not a supported LNURL")
    hrp, data = bech32_decode(normalized)
    if hrp is None or hrp.lower() != "lnurl" or data is None:
        raise ValueError("LNURL encoding is invalid")
    decoded = convertbits(data, 5, 8, False)
    if decoded is None:
        raise ValueError("LNURL data could not be decoded")
    try:
        url = bytes(decoded).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("LNURL does not contain a UTF-8 URL") from exc
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LNURL must contain an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("LNURL contains unsupported URL authority data")
    return url


def lightning_address_from_lnurl(value: str) -> str:
    """Derive an address only from a standard LNURL-pay endpoint path."""

    parsed = urlsplit(decode_lnurl(value))
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(path_parts) == 3 and path_parts[:2] == [".well-known", "lnurlp"]:
        handle = path_parts[2]
    elif len(path_parts) == 2 and path_parts[0] == "lnurlp":
        handle = path_parts[1]
    else:
        raise ValueError("LNURL is not a standard Lightning-address endpoint")
    if not parsed.hostname or parsed.port is not None:
        raise ValueError("LNURL Lightning-address endpoint has an unsupported host")
    return f"{handle}@{parsed.hostname.lower()}"


