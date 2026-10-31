"""Public observation-receipt checks; no commissioning or clock trust decision."""
import hashlib
import json
import re

MAX_INTEGER = 2**53 - 1


def verify_receipt(receipt, subject):
    """Validate the experimental Spurline v1–v3 profile using Stroma events."""
    if not receipt.is_valid() or not subject.is_valid():
        raise ValueError("Invalid event signature or ID")
    r, s = receipt.data(), subject.data()
    if type(r["kind"]) is not int or r["kind"] != 1418 or s["kind"] not in (1415, 1416):
        raise ValueError("Unsupported event kind")
    for field in ("kind", "created_at"):
        if not isinstance(s[field], int) or isinstance(s[field], bool) or not 0 <= s[field] <= MAX_INTEGER:
            raise ValueError("Invalid subject integer")
    body = json.loads(r["content"])
    if not isinstance(body, dict):
        raise ValueError("Invalid receipt body")
    version = body.get("schema_version")
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError("Unsupported receipt version")
    fields = {"schema", "schema_version", "subject_profile", "event_id", "signed_event_digest",
              "observed_at_ms", "issued_at_ms", "clock_uncertainty_ms", "validation",
              "observation_mode", "witness_policy_digest", "authorization_event_id"}
    if version in (2, 3):
        fields |= {"clock_accuracy", "clock_basis"}
    if set(body) != fields or json.dumps(body, sort_keys=True, separators=(",", ":")) != r["content"]:
        raise ValueError("Invalid receipt encoding")
    if (body["schema"] != "org.spurline.observation-receipt"
            or body["subject_profile"] != "nostr-schnorr-secp256k1-v1"
            or body["validation"] != "event-id-and-signature"
            or body["observation_mode"] not in ("live", "backfill")):
        raise ValueError("Unsupported receipt profile")
    for field in ("observed_at_ms", "issued_at_ms"):
        if type(body[field]) is not int or not 0 <= body[field] <= MAX_INTEGER:
            raise ValueError("Invalid receipt time")
    uncertainty = body["clock_uncertainty_ms"]
    if version == 1:
        if (type(uncertainty) is not int or not 0 <= uncertainty <= MAX_INTEGER
                or body["observed_at_ms"] + uncertainty > MAX_INTEGER):
            raise ValueError("Invalid clock uncertainty")
    elif (uncertainty is not None or body["clock_accuracy"] != "unspecified"
          or body["clock_basis"] != ("system-clock" if version == 3 else "ntp-synchronized-system-clock")):
        raise ValueError("Invalid clock basis")
    if (body["observed_at_ms"] > body["issued_at_ms"] or not isinstance(r["created_at"], int)
            or isinstance(r["created_at"], bool)
            or r["created_at"] != body["issued_at_ms"] // 1000):
        raise ValueError("Inconsistent receipt times")
    for field in ("authorization_event_id", "witness_policy_digest"):
        if not isinstance(body[field], str) or not re.fullmatch(r"[0-9a-f]{64}", body[field]):
            raise ValueError("Invalid evidence reference")
    digest = hashlib.sha256(b"spurline.observed-signed-event.v1\x00"
                            + bytes.fromhex(s["id"]) + bytes.fromhex(s["sig"])).hexdigest()
    tags = [["e", s["id"]], ["p", s["pubkey"]], ["k", str(s["kind"])],
            ["t", f"spurline-observation-receipt-v{version}"]]
    if body["event_id"] != s["id"] or body["signed_event_digest"] != digest or r["tags"] != tags:
        raise ValueError("Receipt does not bind this exact signed event")
    return body


def collect_receipts(results, relays, subjects):
    """Deduplicate receipts, retaining retrieval sources separately from signers."""
    receipts = {}
    rejected = set()
    for relay, result in zip(relays, results):
        if isinstance(result, BaseException):
            continue
        for event in result:
            if event.kind != 1418:
                continue
            body = None
            subject_id = next((tag[1] for tag in event.tags if len(tag) > 1 and tag[0] == "e"), None)
            for subject in subjects.get(subject_id, []):
                try:
                    body = verify_receipt(event, subject)
                    break
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
            if body is None:
                rejected.add(event.id)
                continue
            item = receipts.setdefault(event.id, {"id": event.id, "signer": event.pub_key,
                "body": body, "event": event.data(), "sources": []})
            if relay not in item["sources"]:
                item["sources"].append(relay)
    return list(receipts.values()), len(rejected - receipts.keys())
