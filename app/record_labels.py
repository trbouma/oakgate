"""Category paths and content-addressed labels; display never changes identity."""
import hashlib
import json
import re

DIGEST = re.compile(r"[a-fA-F0-9]{64}")
MAX_RECORD_LABEL_LENGTH = 1024
HANDLE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
SHARING_LEAF = re.compile(r'([A-Za-z0-9][A-Za-z0-9_-]{0,63})-([a-fA-F0-9]{64})')


def fingerprint_segment(label):
    parts = str(label).strip('/').split('/')
    return next((p.lower() for p in reversed(parts) if DIGEST.fullmatch(p)), None)


def display_record_label(label, leaf=False):
    name = str(label).strip('/').rsplit('/', 1)[-1]
    shared = SHARING_LEAF.fullmatch(name)
    if shared:
        return shared[1] + '-' + shared[2][:8].upper()
    fingerprint = fingerprint_segment(label)
    if fingerprint:
        return fingerprint[:8].upper()
    return label.strip('/').rsplit('/', 1)[-1] if leaf else label


def content_fingerprint(payload, record_type='generic'):
    return hashlib.sha256(json.dumps({'record_type':record_type, 'payload':payload},
        sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def fingerprint_label(label, fingerprint, sender='unknown-sender'):
    if not isinstance(fingerprint, str) or not DIGEST.fullmatch(fingerprint):
        raise ValueError('Record fingerprint requires the updated Acorn dependency')
    parts = label.strip('/').split('/')
    if any(not p or p in {'.', '..'} or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('Choose a valid record category path')
    if not HANDLE.fullmatch(sender):
        raise ValueError('Invalid sender label')
    # Replace only a recognized provenance leaf, never a meaningful category.
    if DIGEST.fullmatch(parts[-1]) or SHARING_LEAF.fullmatch(parts[-1]):
        parts.pop()
    result = '/'.join([*parts, sender + '-' + fingerprint.lower()])
    if len(result) > MAX_RECORD_LABEL_LENGTH:
        raise ValueError('The category path is too long for a fingerprint label')
    return result


def suggested_record_label(detail):
    sender = detail.get('originator_handle')
    if not isinstance(sender, str) or not HANDLE.fullmatch(sender):
        pubkey = detail.get('originator_pubkey')
        sender = 'sender-' + pubkey[:12].lower() if isinstance(pubkey, str) and DIGEST.fullmatch(pubkey) else 'unknown-sender'
    return fingerprint_label(detail['label'], detail.get('sharing_fingerprint'), sender)


def updated_record_label(detail, payload, attachment=None, explicit_label=None):
    old = detail['label']
    if explicit_label is not None and explicit_label.strip() != old:
        label = explicit_label.strip()
        if not label or len(label)>MAX_RECORD_LABEL_LENGTH or any(ord(c)<32 for c in label):
            raise ValueError('Choose a record label of 1–1024 characters')
        return label
    # The sharing label identifies receipt provenance, not the edited content.
    return old
