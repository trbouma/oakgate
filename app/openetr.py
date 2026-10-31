"""Small, read-only OpenETR projection for Safebox record pages.

This adapter retrieves evidence and applies Core Record Ruleset 1.0. It does
not publish events or make recognition or legal-validity claims.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from stroma import Event, RelayClient
from stroma.nip19 import Entities
from app.openetr_rules import evaluate_core_record, POSITION_LABELS


ANCHOR_KIND = 1415
CONTROL_KIND = 1416
PROFILE_KIND = 0
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
HEX_PUBKEY_PATTERN = re.compile(r"[0-9a-f]{64}")

ACTION_LABELS = {
    "notice": "Publisher notice",
    "issue": "Anchor recorded",
    "initiate": "Transfer initiated",
    "accept": "Transfer accepted",
    "terminate": "Control terminated",
    "attest": "Attestation recorded",
    "encumber": "Encumbrance recorded",
    "discharge": "Encumbrance discharged",
    "redeem": "Presented for redemption",
}


def derive_consequential_state(
    artifact_id: str,
    dcr_records: Iterable[Event],
) -> dict[str, Any]:
    """Evaluate supplied evidence under Core Record Ruleset 1.0."""
    return evaluate_core_record(artifact_id, dcr_records)


def build_digital_controllable_record(
    artifact_id: str,
    records: Iterable[Event],
) -> dict[str, Any]:
    """Build the inspectable DCR layer without asserting derived state.

    The Digital Artifact is the digest-identified content. This returned
    structure is the distinct signed evidence layer concerning that artifact.
    Ruleset evaluation is returned separately; no authority is inferred here.
    """

    normalized_artifact_id = str(artifact_id or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized_artifact_id):
        raise ValueError(
            "OpenETR artifact digest must be a 64-character SHA-256 value"
        )
    record_list = list(records)
    return {
        "status": "candidate",
        "artifact_id": normalized_artifact_id,
        "record_count": len(record_list),
        "record_event_ids": [record.id for record in record_list],
    }


def _tag_value(event: Event, name: str) -> str | None:
    for tag in event.tags or []:
        if len(tag) >= 2 and tag[0] == name:
            return str(tag[1])
    return None


def _npub(pubkey_hex: str) -> str:
    try:
        return Entities.encode("npub", pubkey_hex)
    except Exception:
        return pubkey_hex


def _timestamp(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _display_time(value: Any) -> str:
    seconds = _timestamp(value)
    if not seconds:
        return "Unknown"
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OverflowError, OSError):
        return "Outside displayable range"


def _event_is_valid(event: Event) -> bool:
    try:
        return bool(event.is_valid())
    except Exception:
        return False


def _event_view(event: Event) -> dict[str, Any]:
    action = (_tag_value(event, "action") or "").strip().lower()
    return {
        "id": event.id,
        "author": _npub(event.pub_key),
        "author_hex": event.pub_key,
        "created_at": _display_time(event.created_at),
        "kind": event.kind,
        "action": action or "unknown",
        "action_label": ACTION_LABELS.get(
            action,
            "Unrecognized evidence event",
        ),
        "content": event.content or "",
        "notice_type": _tag_value(event, "notice_type"),
        "prior_event_id": _tag_value(event, "e"),
        # The legacy wire tag remains ``origin``; the application model uses
        # current Anchor Event terminology.
        "anchor_event_id": _tag_value(event, "origin"),
        "participant": (
            _npub(_tag_value(event, "p")) if _tag_value(event, "p") else None
        ),
    }


def _profile_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    return cleaned[:limit]


def _profile_url(value: Any) -> str | None:
    candidate = _profile_text(value, limit=2048)
    if candidate is None:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def build_signer_profile(
    pubkey_hex: str,
    events: Iterable[Event],
) -> dict[str, Any] | None:
    """Return the latest valid, well-formed kind-0 profile for one signer."""

    normalized_pubkey = str(pubkey_hex or "").strip().lower()
    if not HEX_PUBKEY_PATTERN.fullmatch(normalized_pubkey):
        return None
    candidates = [
        event
        for event in events
        if event.kind == PROFILE_KIND
        and str(event.pub_key or "").lower() == normalized_pubkey
        and _event_is_valid(event)
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (_timestamp(item.created_at), item.id))
    try:
        payload = json.loads(latest.content or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    name = _profile_text(payload.get("name"), limit=100)
    display_name = _profile_text(
        payload.get("display_name") or payload.get("displayName"),
        limit=100,
    )
    return {
        "event_id": latest.id,
        "author": _npub(normalized_pubkey),
        "created_at": _display_time(latest.created_at),
        "display_name": display_name,
        "name": name if name != display_name else None,
        "about": _profile_text(payload.get("about"), limit=500),
        "address": _profile_text(payload.get("address"), limit=500),
        "nip05": _profile_text(payload.get("nip05"), limit=254),
        "lightning_address": _profile_text(payload.get("lud16"), limit=254),
        "website": _profile_url(payload.get("website")),
        "picture": _profile_url(payload.get("picture")),
    }


def build_openetr_history(
    digest: str,
    events: Iterable[Event],
    relays: Iterable[str],
) -> dict[str, Any]:
    """Adapt ruleset results to the existing record-page presentation."""
    event_list = list(events)
    result = evaluate_core_record(digest, event_list)
    normalized_digest = result["artifact"]["digest"]
    by_id = {}
    for event in event_list:
        # Prefer authenticated copies when duplicate claimed IDs occur.
        if event.id not in by_id or _event_is_valid(event):
            by_id[event.id] = event
    graphs = []
    for candidate in result["candidates"]:
        anchor = by_id[candidate["anchor_event_id"]]
        notices = [by_id[key] for key in candidate["notice_event_ids"]]
        graphs.append({
            "artifact": {"id": normalized_digest, "identity_method": "sha256"},
            "digital_controllable_record": build_digital_controllable_record(
                normalized_digest, [anchor, *notices]),
            "anchor": _event_view(anchor), "signer_profile": None,
            "signer_profile_error": None,
            "controls": [_event_view(event) for event in notices],
            "warnings": [],
            "consequential_state": candidate,
            "publisher_position_label": POSITION_LABELS[candidate["publisher_position"]],
            "recognition": {"status": "not_evaluated", "basis": None},
            "effect": {"status": "not_evaluated", "value": None, "purpose": None},
        })
    warnings = []
    if len(graphs) > 1:
        warnings.append(f"{len(graphs)} candidate Anchor Events were found. No candidate was selected as authoritative.")
    if result["non_qualifying_evidence"]:
        warnings.append("Some supplied evidence did not qualify under this ruleset. Inspect the findings below.")
    result["retrieval"]["sources"] = list(relays)
    return {
        "digest": normalized_digest,
        "relays": tuple(result["retrieval"]["sources"]),
        "candidate_graphs": graphs,
        "unlinked_events": [_event_view(by_id[key]) for key in sorted({
            item["event_id"] for item in result["non_qualifying_evidence"]})],
        "invalid_event_count": sum(f["code"] in {"invalid_event_id", "invalid_signature"}
                                   for f in result["findings"]),
        "warnings": warnings, "error": None, "verification": result,
    }


def unavailable_openetr_history(digest: str, relays: Iterable[str]) -> dict[str, Any]:
    """Represent retrieval failure without asserting absence of an anchor."""
    history = build_openetr_history(digest, [], relays)
    result = history["verification"]
    result["aggregate_state"] = "unverifiable"
    result["findings"] = [{"code": "retrieval_incomplete", "event_id": None}]
    result["retrieval"].update({"mode": "relay_discovery", "failed": True,
                               "ended_at": datetime.now(timezone.utc).isoformat()})
    history["error"] = "OpenETR verification is temporarily unavailable."
    return history


async def query_openetr_history(digest, relays, *, timeout=5.0, limit=100, digest_source="supplied"):
    import asyncio
    import aiohttp
    from app.identity import PublicResolver
    from app.zaps import public_relay

    if not SHA256_PATTERN.fullmatch(digest):
        raise ValueError("Invalid artifact digest")
    if digest_source not in {"supplied", "computed"}:
        raise ValueError("Invalid digest source")
    relays = tuple(public_relay(url) for url in relays)
    async def no_redirect(session, context, params):
        raise ValueError("Relay redirects are not supported")
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(no_redirect)
    def session_factory(**kwargs):
        return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver()),
                                     trace_configs=[trace], trust_env=False, **kwargs)
    event_filter = {"#o": [digest], "kinds": [ANCHOR_KIND, CONTROL_KIND], "limit": limit}
    async def query(relay, filters):
        async with asyncio.timeout(timeout):
            return await RelayClient(relay, timeout=timeout, max_msg_size=262144,
                                     session_factory=session_factory).query(filters)
    started = datetime.now(timezone.utc).isoformat()
    results = await asyncio.gather(*(query(relay, event_filter) for relay in relays), return_exceptions=True)
    if all(isinstance(result, BaseException) for result in results):
        history = unavailable_openetr_history(digest, relays)
        history["verification"]["artifact"]["digest_source"] = digest_source
        return history
    events = [event for result in results if not isinstance(result, BaseException)
              for event in result if event.kind in (ANCHOR_KIND, CONTROL_KIND)
              and _tag_value(event, "o") == digest]
    history = build_openetr_history(digest, events, relays)
    history["verification"]["retrieval"].update({"mode": "relay_discovery", "filters": [event_filter], "started_at": started,
        "ended_at": datetime.now(timezone.utc).isoformat(), "timeout_seconds": timeout,
        "limitations": ["Bounded queries; no guarantee of global completeness."]})
    history["verification"]["artifact"]["digest_source"] = digest_source
    history["verification"]["findings"].append({"code": "retrieval_incomplete", "event_id": None})
    if any(isinstance(result, BaseException) for result in results):
        history["warnings"].append("Some relays were unavailable; the evidence is incomplete.")
    graphs = history["candidate_graphs"]
    if graphs:
        profile_filter = {"kinds": [PROFILE_KIND],
                          "authors": sorted({g["anchor"]["author_hex"] for g in graphs}),
                          "limit": min(200, max(10, len(graphs) * 3))}
        from app.openetr_witnesses import collect_receipts
        subject_ids = sorted({event["id"] for graph in graphs
                              for event in [graph["anchor"], *graph["controls"]]})
        selected_ids = subject_ids[:200]
        witness_filter = {"kinds": [1418], "#e": selected_ids, "limit": limit}
        combined = await asyncio.gather(
            *(query(relay, profile_filter) for relay in relays),
            *(query(relay, witness_filter) for relay in relays), return_exceptions=True)
        profiles, witness_results = combined[:len(relays)], combined[len(relays):]
        subjects = {}
        for event in events:
            if event.id in selected_ids:
                subjects.setdefault(event.id, []).append(event)
        receipts, rejected = collect_receipts(witness_results, relays, subjects)
        witness_warnings = []
        if any(isinstance(result, BaseException) for result in witness_results):
            witness_warnings.append("Some witness sources were unavailable; receipt discovery is incomplete.")
        if len(subject_ids) > 200 or any(not isinstance(result, BaseException) and len(result) >= limit
                                       for result in witness_results):
            witness_warnings.append("Witness discovery reached a query limit; additional receipts may exist.")
        if rejected:
            witness_warnings.append("Some witness events failed the supported receipt checks and are not displayed.")
        for receipt in receipts:
            receipt["signer_npub"] = _npub(receipt["signer"])
            for field in ("observed_at_ms", "issued_at_ms"):
                receipt[field + "_display"] = _display_time(receipt["body"][field] // 1000)
        profile_events = [event for result in profiles if not isinstance(result, BaseException)
                          for event in result]
        for graph in graphs:
            graph_ids = {event["id"] for event in [graph["anchor"], *graph["controls"]]}
            graph["witnesses"] = [receipt for receipt in receipts if receipt["body"]["event_id"] in graph_ids]
            graph["witness_warnings"] = witness_warnings
            graph["signer_profile"] = build_signer_profile(graph["anchor"]["author_hex"], profile_events)
            if any(isinstance(result, BaseException) for result in profiles):
                graph["signer_profile_error"] = "Some signer profile sources were unavailable."
    return history
