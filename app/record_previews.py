"""Presentation-only previews adapted from Safebox Web (MIT, Tim Bouma).

No key operations, network calls or credential-verification claims belong here.
"""
import base64
import io
import json
import re
import mimetypes
import zipfile
from pathlib import Path
from urllib.parse import quote
import cbor2
import qrcode
import qrcode.image.svg
from aztec_code_generator import AztecCode

INLINE_BLOB_IMAGE_TYPES = frozenset(
    {
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
PKPASS_MIME_TYPE = "application/vnd.apple.pkpass"
VC_MIME_TYPE = "application/vc"
VP_MIME_TYPE = "application/vp"
VC_JWT_MIME_TYPE = "application/vc+jwt"
VC_SD_JWT_MIME_TYPE = "application/vc+sd-jwt"
VC_COSE_MIME_TYPE = "application/vc+cose"
MDOC_CBOR_MIME_TYPE = "application/mdoc+cbor"
EUDI_PID_DOC_TYPE = "eu.europa.ec.eudi.pid.1"
MDL_DOC_TYPE = "org.iso.18013.5.1.mDL"
MDL_NAMESPACE = "org.iso.18013.5.1"
JSON_CREDENTIAL_PREVIEW_TYPES = frozenset({VC_MIME_TYPE, VP_MIME_TYPE})
JSON_CREDENTIAL_PREVIEW_MAX_BYTES = 1024 * 1024
JSON_CREDENTIAL_PREVIEW_MAX_ROWS = 80
JSON_CREDENTIAL_PREVIEW_MAX_CLAIMS = 40
MDOC_PREVIEW_MAX_BYTES = 1024 * 1024
MDOC_PREVIEW_MAX_ROWS = 100
EUDI_PID_FIELD_LABELS = {
    "family_name": "Family name",
    "given_name": "Given name",
    "birth_date": "Date of birth",
    "place_of_birth": "Place of birth",
    "nationality": "Nationality",
    "expiry_date": "Expiry date",
    "issuing_authority": "Issuing authority",
    "issuing_country": "Issuing country",
    "issuance_date": "Issuance date",
    "resident_address": "Address",
    "resident_country": "Country of residence",
    "resident_state": "State or region",
    "resident_city": "City",
    "resident_postal_code": "Postal code",
    "resident_street": "Street",
    "resident_house_number": "House number",
    "document_number": "Document number",
    "personal_administrative_number": "Administrative number",
    "family_name_birth": "Family name at birth",
    "given_name_birth": "Given name at birth",
    "sex": "Sex",
    "email_address": "Email address",
    "mobile_phone_number": "Mobile phone number",
}
MDL_FIELD_LABELS = {
    "family_name": "Family name",
    "given_name": "Given name",
    "birth_date": "Date of birth",
    "issue_date": "Issue date",
    "expiry_date": "Expiry date",
    "issuing_country": "Issuing country",
    "issuing_authority": "Issuing authority",
    "document_number": "Licence number",
    "portrait": "Portrait",
    "driving_privileges": "Driving privileges",
    "un_distinguishing_sign": "Distinguishing sign",
    "age_over_18": "Over 18",
    "age_over_21": "Over 21",
    "age_in_years": "Age in years",
    "age_birth_year": "Birth year",
    "nationality": "Nationality",
    "sex": "Sex",
    "place_of_birth": "Place of birth",
    "resident_address": "Address",
    "resident_city": "City",
    "resident_state": "State or region",
    "resident_postal_code": "Postal code",
    "resident_country": "Country of residence",
    "height": "Height",
    "weight": "Weight",
    "eye_colour": "Eye colour",
    "hair_colour": "Hair colour",
    "family_name_national_character": "Family name (national characters)",
    "given_name_national_character": "Given name (national characters)",
    "signature_usual_mark": "Signature",
}
EFFECTIVE_MIME_DOWNLOAD_EXTENSIONS = {
    VC_MIME_TYPE: ".json",
    VP_MIME_TYPE: ".json",
    VC_JWT_MIME_TYPE: ".jwt",
    "application/vp+jwt": ".jwt",
    VC_SD_JWT_MIME_TYPE: ".sd-jwt",
    "application/vp+sd-jwt": ".sd-jwt",
    VC_COSE_MIME_TYPE: ".cose",
    "application/vp+cose": ".cose",
    MDOC_CBOR_MIME_TYPE: ".mdoc",
    PKPASS_MIME_TYPE: ".pkpass",
}
PKPASS_PREVIEW_MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
PKPASS_PREVIEW_MAX_MEMBER_BYTES = 2 * 1024 * 1024
PKPASS_PREVIEW_MAX_TOTAL_BYTES = 12 * 1024 * 1024
PKPASS_PREVIEW_IMAGE_NAMES = (
    "strip.png",
    "strip@2x.png",
    "thumbnail.png",
    "thumbnail@2x.png",
    "logo.png",
    "logo@2x.png",
    "icon.png",
    "icon@2x.png",
)


def _qr_svg(payload):
    if len(payload.encode()) > 2048:
        return None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode")

def _normalize_media_type(media_type: str | None) -> str | None:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    return normalized or None

def _record_original_filename(record_value) -> str:
    payload = getattr(record_value, "payload", None)
    if isinstance(payload, dict):
        return str(payload.get("filename") or "")
    return ""

def _record_has_blob(record_value) -> bool:
    """Recognize both identity-resolved and legacy URL-backed attachments."""

    return bool(
        getattr(record_value, "blobsha256", None)
        or getattr(record_value, "blobref", None)
    )

def _effective_blob_media_type(media_type: str | None, record_value=None) -> str:
    """Prefer explicit Record File metadata when byte sniffing is ambiguous."""

    normalized = _normalize_media_type(media_type) or "application/octet-stream"
    if record_value is not None:
        payload = getattr(record_value, "payload", None)
        if isinstance(payload, dict):
            payload_type = _normalize_media_type(payload.get("content_type"))
            if payload_type == PKPASS_MIME_TYPE:
                return PKPASS_MIME_TYPE
        if _record_original_filename(record_value).lower().endswith(".pkpass"):
            return PKPASS_MIME_TYPE
    return normalized or "application/octet-stream"

def _pkpass_asset_data_url(archive: zipfile.ZipFile, name: str) -> str | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > PKPASS_PREVIEW_MAX_MEMBER_BYTES:
        return None
    data = archive.read(info)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    else:
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"

def _pkpass_field_rows(pass_json: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pass_sections = (
        "boardingPass",
        "coupon",
        "eventTicket",
        "generic",
        "storeCard",
    )
    field_sections = (
        "headerFields",
        "primaryFields",
        "secondaryFields",
        "auxiliaryFields",
        "backFields",
    )
    for pass_section in pass_sections:
        section = pass_json.get(pass_section)
        if not isinstance(section, dict):
            continue
        for field_section in field_sections:
            fields = section.get(field_section)
            if not isinstance(fields, list):
                continue
            for field in fields:
                if not isinstance(field, dict):
                    continue
                value = field.get("value")
                if value is None:
                    continue
                label = str(field.get("label") or field.get("key") or "").strip()
                rows.append(
                    {
                        "label": label[:80],
                        "value": str(value).strip()[:240],
                    }
                )
                if len(rows) >= 10:
                    return rows
    return rows

def _pkpass_barcode_svg(format_name: str, message: str, encoding: str) -> str | None:
    if len(message.encode()) > 2048:
        return None
    if format_name == "QR":
        return _qr_svg(message)
    if format_name == "Aztec":
        try:
            svg = AztecCode(message, encoding=encoding or None).svg()
        except (LookupError, TypeError, ValueError):
            return None
        svg = re.sub(r"^<\?xml[^>]*\?>", "", svg, count=1)
        return svg.replace("<svg ", '<svg class="pkpass-barcode-symbol" ', 1)
    return None

def _pkpass_barcode(pass_json: dict) -> dict[str, str | None] | None:
    candidates = pass_json.get("barcodes")
    if isinstance(candidates, list) and candidates:
        barcode = candidates[0]
    else:
        barcode = pass_json.get("barcode")
    if not isinstance(barcode, dict):
        return None
    message = str(barcode.get("message") or "").strip()
    if not message:
        return None
    format_name = str(barcode.get("format") or "barcode").replace(
        "PKBarcodeFormat", ""
    )
    encoding = str(barcode.get("messageEncoding") or "").strip()
    alt_text = str(barcode.get("altText") or "").strip()
    return {
        "format": format_name,
        "message": message[:240],
        "alt_text": alt_text[:120],
        "symbol": _pkpass_barcode_svg(format_name, message, encoding),
    }

def _pkpass_preview(blob_data: bytes | None) -> dict | None:
    if not blob_data or len(blob_data) > PKPASS_PREVIEW_MAX_ARCHIVE_BYTES:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(blob_data)) as archive:
            total_size = 0
            for info in archive.infolist():
                name = info.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    return None
                total_size += max(0, int(info.file_size))
                if (
                    info.file_size > PKPASS_PREVIEW_MAX_MEMBER_BYTES
                    or total_size > PKPASS_PREVIEW_MAX_TOTAL_BYTES
                ):
                    return None
            pass_info = archive.getinfo("pass.json")
            if pass_info.file_size > PKPASS_PREVIEW_MAX_MEMBER_BYTES:
                return None
            pass_json = json.loads(archive.read(pass_info).decode("utf-8"))
            if not isinstance(pass_json, dict):
                return None
            images = {
                name.split(".", 1)[0].replace("@2x", ""): data_url
                for name in PKPASS_PREVIEW_IMAGE_NAMES
                if (data_url := _pkpass_asset_data_url(archive, name))
            }
            return {
                "organization": str(pass_json.get("organizationName") or "").strip(),
                "description": str(pass_json.get("description") or "").strip(),
                "logo_text": str(pass_json.get("logoText") or "").strip(),
                "serial": str(pass_json.get("serialNumber") or "").strip(),
                "fields": _pkpass_field_rows(pass_json),
                "barcode": _pkpass_barcode(pass_json),
                "images": images,
            }
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return None

def _json_credential_preview_rows(
    value,
    *,
    prefix: str = "",
    depth: int = 0,
    rows: list[dict[str, str | int | None]] | None = None,
) -> list[dict[str, str | int | None]]:
    if rows is None:
        rows = []
    if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_ROWS:
        return rows
    if isinstance(value, dict):
        for key, child in value.items():
            if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_ROWS:
                break
            label = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, (dict, list)):
                rows.append({"key": label, "value": None, "depth": min(depth, 6)})
                _json_credential_preview_rows(
                    child,
                    prefix=label,
                    depth=depth + 1,
                    rows=rows,
                )
            else:
                rows.append(
                    {
                        "key": label,
                        "value": _json_preview_scalar(child),
                        "depth": min(depth, 6),
                    }
                )
        return rows
    if isinstance(value, list):
        for index, child in enumerate(value):
            if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_ROWS:
                break
            label = f"{prefix}[{index}]" if prefix else f"[{index}]"
            if isinstance(child, (dict, list)):
                rows.append({"key": label, "value": None, "depth": min(depth, 6)})
                _json_credential_preview_rows(
                    child,
                    prefix=label,
                    depth=depth + 1,
                    rows=rows,
                )
            else:
                rows.append(
                    {
                        "key": label,
                        "value": _json_preview_scalar(child),
                        "depth": min(depth, 6),
                    }
                )
        return rows
    rows.append(
        {
            "key": prefix or "value",
            "value": _json_preview_scalar(value),
            "depth": min(depth, 6),
        }
    )
    return rows

def _json_preview_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)[:500]

def _json_credential_label(value: object) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    text = re.sub(r"[_-]+", " ", text).strip()
    return (text[:1].upper() + text[1:])[:120] if text else "Claim"

def _json_credential_display_value(value) -> str:
    if isinstance(value, dict):
        identifier = value.get("id")
        name = value.get("name")
        if name and identifier:
            return f"{_json_preview_scalar(name)} ({_json_preview_scalar(identifier)})"
        if name or identifier:
            return _json_preview_scalar(name or identifier)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:500]
    if isinstance(value, list):
        return ", ".join(_json_preview_scalar(item) for item in value)[:500]
    return _json_preview_scalar(value)

def _json_credential_claim_label(prefix: tuple[str, ...]) -> str:
    if not prefix:
        return "Claim"
    return " ".join(
        [
            prefix[0],
            *(value[:1].lower() + value[1:] for value in prefix[1:]),
        ]
    )

def _json_credential_claim_rows(
    value,
    *,
    prefix: tuple[str, ...] = (),
    rows: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    if rows is None:
        rows = []
    if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_CLAIMS:
        return rows
    if isinstance(value, dict):
        for key, child in value.items():
            if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_CLAIMS:
                break
            if str(key) == "id":
                continue
            _json_credential_claim_rows(
                child,
                prefix=(*prefix, _json_credential_label(key)),
                rows=rows,
            )
        return rows
    if isinstance(value, list):
        if all(not isinstance(child, (dict, list)) for child in value):
            rows.append({
                "label": _json_credential_claim_label(prefix),
                "value": _json_credential_display_value(value),
            })
            return rows
        for index, child in enumerate(value, start=1):
            if len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_CLAIMS:
                break
            item_prefix = prefix if len(value) == 1 else (*prefix, str(index))
            _json_credential_claim_rows(child, prefix=item_prefix, rows=rows)
        return rows
    rows.append({
        "label": _json_credential_claim_label(prefix),
        "value": _json_credential_display_value(value),
    })
    return rows

def _json_credential_types(document: dict) -> list[str]:
    raw_types = document.get("type")
    if isinstance(raw_types, list):
        return [str(value) for value in raw_types if str(value).strip()]
    if raw_types is not None and str(raw_types).strip():
        return [str(raw_types)]
    return []

def _json_credential_title(document: dict, *, kind: str) -> str:
    generic_type = "VerifiablePresentation" if kind == "vp" else "VerifiableCredential"
    specific_types = [
        value for value in _json_credential_types(document) if value != generic_type
    ]
    if specific_types:
        return _json_credential_label(specific_types[-1])
    return "W3C Verifiable Presentation" if kind == "vp" else "W3C Verifiable Credential"

def _json_credential_preview(blob_data: bytes | None) -> dict | None:
    if not blob_data or len(blob_data) > JSON_CREDENTIAL_PREVIEW_MAX_BYTES:
        return None
    try:
        document = json.loads(blob_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    rows = _json_credential_preview_rows(document)
    credential_types = _json_credential_types(document)
    kind = (
        "vp"
        if "VerifiablePresentation" in credential_types
        or "verifiableCredential" in document
        else "vc"
    )
    summary = []

    def add_summary(label: str, value) -> None:
        if value is None or value == "" or value == []:
            return
        summary.append({
            "label": label,
            "value": _json_credential_display_value(value),
        })

    if kind == "vp":
        add_summary("Holder", document.get("holder"))
        credentials = document.get("verifiableCredential")
        if isinstance(credentials, list):
            add_summary("Credentials", len(credentials))
        elif credentials is not None:
            add_summary("Credentials", 1)
    else:
        add_summary("Issuer", document.get("issuer"))
        add_summary("Credential ID", document.get("id"))
        add_summary("Valid from", document.get("validFrom") or document.get("issuanceDate"))
        add_summary("Valid until", document.get("validUntil") or document.get("expirationDate"))
        subjects = document.get("credentialSubject")
        subject_values = subjects if isinstance(subjects, list) else [subjects]
        subject_ids = [
            subject.get("id")
            for subject in subject_values
            if isinstance(subject, dict) and subject.get("id")
        ]
        add_summary("Subject", subject_ids)
    claims_source = document.get("credentialSubject") if kind == "vc" else None
    claims = (
        _json_credential_claim_rows(claims_source)
        if claims_source is not None
        else []
    )
    return {
        "kind": kind,
        "title": _json_credential_title(document, kind=kind),
        "summary": summary,
        "claims": claims,
        "rows": rows,
        "truncated": len(rows) >= JSON_CREDENTIAL_PREVIEW_MAX_ROWS,
        "claims_truncated": len(claims) >= JSON_CREDENTIAL_PREVIEW_MAX_CLAIMS,
    }

def _mdoc_preview_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bytes):
        prefix = value[:16].hex()
        suffix = "..." if len(value) > 16 else ""
        return f"bytes({len(value)}) 0x{prefix}{suffix}"
    if isinstance(value, cbor2.CBORTag):
        return f"CBOR tag {value.tag}: {_mdoc_preview_scalar(value.value)}"
    return str(value)[:500]

def _mdoc_embedded_map(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, cbor2.CBORTag):
        value = value.value
    if not isinstance(value, bytes):
        return None
    try:
        decoded = cbor2.loads(value)
    except (cbor2.CBORDecodeError, ValueError, TypeError):
        return None
    return decoded if isinstance(decoded, dict) else None

def _mdoc_display_value(value) -> str:
    if isinstance(value, cbor2.CBORTag):
        return _mdoc_display_value(value.value)
    if isinstance(value, bytes):
        return f"Binary data ({len(value)} bytes)"
    if isinstance(value, dict):
        return ", ".join(
            f"{_mdoc_preview_scalar(key)}: {_mdoc_display_value(child)}"
            for key, child in value.items()
        )[:500]
    if isinstance(value, (list, tuple)):
        return ", ".join(_mdoc_display_value(child) for child in value)[:500]
    return _mdoc_preview_scalar(value)

def _mdoc_preview_fields(
    first_document: dict | None,
    namespace: str,
    labels: dict[str, str],
) -> list[dict[str, str]]:
    if not isinstance(first_document, dict):
        return []
    issuer_signed = first_document.get("issuerSigned")
    if not isinstance(issuer_signed, dict):
        return []
    namespaces = issuer_signed.get("nameSpaces")
    if not isinstance(namespaces, dict):
        return []
    elements = namespaces.get(namespace)
    if not isinstance(elements, (list, tuple)):
        return []

    fields = []
    for encoded_element in elements:
        element = _mdoc_embedded_map(encoded_element)
        if element is None:
            continue
        identifier = str(element.get("elementIdentifier") or "").strip()
        if not identifier or "elementValue" not in element:
            continue
        fields.append(
            {
                "identifier": identifier,
                "label": labels.get(
                    identifier, identifier.replace("_", " ").capitalize()
                ),
                "value": _mdoc_display_value(element["elementValue"]),
            }
        )
    return fields

def _mdoc_preview_rows(
    value,
    *,
    prefix: str = "",
    depth: int = 0,
    rows: list[dict[str, str | int | None]] | None = None,
) -> list[dict[str, str | int | None]]:
    if rows is None:
        rows = []
    if len(rows) >= MDOC_PREVIEW_MAX_ROWS:
        return rows
    if isinstance(value, cbor2.CBORTag):
        label = prefix or f"tag({value.tag})"
        rows.append(
            {
                "key": f"{label} tag",
                "value": str(value.tag),
                "depth": min(depth, 6),
            }
        )
        return _mdoc_preview_rows(
            value.value,
            prefix=f"{label}.value",
            depth=depth + 1,
            rows=rows,
        )
    if isinstance(value, dict):
        for key, child in value.items():
            if len(rows) >= MDOC_PREVIEW_MAX_ROWS:
                break
            key_label = _mdoc_preview_scalar(key)
            label = f"{prefix}.{key_label}" if prefix else key_label
            if isinstance(child, (dict, list, tuple, cbor2.CBORTag)):
                rows.append({"key": label, "value": None, "depth": min(depth, 6)})
                _mdoc_preview_rows(
                    child,
                    prefix=label,
                    depth=depth + 1,
                    rows=rows,
                )
            else:
                rows.append(
                    {
                        "key": label,
                        "value": _mdoc_preview_scalar(child),
                        "depth": min(depth, 6),
                    }
                )
        return rows
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            if len(rows) >= MDOC_PREVIEW_MAX_ROWS:
                break
            label = f"{prefix}[{index}]" if prefix else f"[{index}]"
            if isinstance(child, (dict, list, tuple, cbor2.CBORTag)):
                rows.append({"key": label, "value": None, "depth": min(depth, 6)})
                _mdoc_preview_rows(
                    child,
                    prefix=label,
                    depth=depth + 1,
                    rows=rows,
                )
            else:
                rows.append(
                    {
                        "key": label,
                        "value": _mdoc_preview_scalar(child),
                        "depth": min(depth, 6),
                    }
                )
        return rows
    rows.append(
        {
            "key": prefix or "value",
            "value": _mdoc_preview_scalar(value),
            "depth": min(depth, 6),
        }
    )
    return rows

def _mdoc_preview(blob_data: bytes | None) -> dict | None:
    if not blob_data or len(blob_data) > MDOC_PREVIEW_MAX_BYTES:
        return None
    try:
        document = cbor2.loads(blob_data)
    except (cbor2.CBORDecodeError, ValueError, TypeError):
        return None
    documents = document.get("documents") if isinstance(document, dict) else None
    document_count = len(documents) if isinstance(documents, list) else None
    first_document = (
        documents[0]
        if isinstance(documents, list) and documents and isinstance(documents[0], dict)
        else None
    )
    doc_type = (
        str(first_document.get("docType") or "")
        if isinstance(first_document, dict)
        else ""
    )
    status = document.get("status") if isinstance(document, dict) else None
    rows = _mdoc_preview_rows(document)
    field_labels = (
        EUDI_PID_FIELD_LABELS
        if doc_type == EUDI_PID_DOC_TYPE
        else MDL_FIELD_LABELS
        if doc_type == MDL_DOC_TYPE
        else None
    )
    field_namespace = (
        EUDI_PID_DOC_TYPE
        if doc_type == EUDI_PID_DOC_TYPE
        else MDL_NAMESPACE
        if doc_type == MDL_DOC_TYPE
        else None
    )
    return {
        "doc_type": doc_type,
        "credential_kind": (
            "eudi_pid"
            if doc_type == EUDI_PID_DOC_TYPE
            else "mdl"
            if doc_type == MDL_DOC_TYPE
            else "mdoc"
        ),
        "document_count": document_count,
        "status": _mdoc_preview_scalar(status) if status is not None else None,
        "credential_fields": (
            _mdoc_preview_fields(first_document, field_namespace, field_labels)
            if field_namespace is not None and field_labels is not None
            else []
        ),
        "rows": rows,
        "truncated": len(rows) >= MDOC_PREVIEW_MAX_ROWS,
    }

def _blob_preview_kind(media_type: str | None) -> str | None:
    """Return a narrowly allowlisted browser-native preview type."""

    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    if normalized in INLINE_BLOB_IMAGE_TYPES:
        return "image"
    if normalized == "application/pdf":
        return "pdf"
    return None

def _blob_recognition_fingerprint(digest: str | None) -> str | None:
    """Return an eight-character display fingerprint for a plaintext SHA-256."""

    normalized = str(digest or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", normalized) is None:
        return None
    return normalized[:8].upper()

def _blob_download_headers(
    label: str,
    media_type: str | None,
    *,
    inline: bool = False,
) -> dict[str, str]:
    """Return an injection-safe filename with UTF-8 label support."""

    normalized_media_type = _normalize_media_type(media_type)
    extension = (
        EFFECTIVE_MIME_DOWNLOAD_EXTENSIONS.get(normalized_media_type or "")
        or mimetypes.guess_extension(normalized_media_type or "")
        or ".bin"
    )
    filename = label if label.lower().endswith(extension.lower()) else label + extension
    fallback_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._") or "acorn-blob"
    fallback = (
        fallback_stem
        if fallback_stem.lower().endswith(extension.lower())
        else fallback_stem + extension
    )
    disposition = "inline" if inline else "attachment"
    return {
        "Content-Disposition": (
            f'{disposition}; filename="{fallback[:180]}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }
