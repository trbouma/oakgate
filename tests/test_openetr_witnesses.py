import asyncio
import hashlib
import json

import pytest
from jinja2 import Environment, FileSystemLoader
from app import openetr
from app.openetr_witnesses import verify_receipt, collect_receipts
from test_openetr import signed, DIGEST


def receipt(subject, version=3, **changes):
    body = dict(schema="org.spurline.observation-receipt", schema_version=version,
        subject_profile="nostr-schnorr-secp256k1-v1", event_id=subject.id,
        signed_event_digest=hashlib.sha256(b"spurline.observed-signed-event.v1\x00"
            + bytes.fromhex(subject.id) + bytes.fromhex(subject.sig)).hexdigest(),
        observed_at_ms=200000, issued_at_ms=201000, clock_uncertainty_ms=10 if version == 1 else None,
        validation="event-id-and-signature", observation_mode="live",
        witness_policy_digest="ab" * 32, authorization_event_id="cd" * 32)
    if version in (2, 3):
        body.update(clock_accuracy="unspecified",
                    clock_basis="system-clock" if version == 3 else "ntp-synchronized-system-clock")
    body.update(changes)
    return signed(1418, key="02" * 32, time=201,
        tags=[["e", subject.id], ["p", subject.pub_key], ["k", str(subject.kind)],
              ["t", f"spurline-observation-receipt-v{version}"]],
        content=json.dumps(body, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("version", [1, 2, 3])
def test_supported_profiles(version):
    subject = signed()
    assert verify_receipt(receipt(subject, version), subject)["schema_version"] == version


@pytest.mark.parametrize("changes", [dict(signed_event_digest="00" * 32),
    dict(event_id="00" * 32), dict(observed_at_ms=202000), dict(issued_at_ms=True),
    dict(clock_uncertainty_ms=0), dict(schema_version=4), dict(extra="unrecognized"),
    dict(authorization_event_id="invalid")])
def test_reject_invalid_profile(changes):
    subject = signed()
    with pytest.raises(ValueError):
        verify_receipt(receipt(subject, **changes), subject)


def test_signature_and_deduplication():
    subject = signed()
    event = receipt(subject)
    items, rejected = collect_receipts([[event], [event]], ["one", "two"], {subject.id: [subject]})
    assert rejected == 0 and len(items) == 1
    assert items[0]["sources"] == ["one", "two"]
    event.content = "tampered"
    with pytest.raises(ValueError):
        verify_receipt(event, subject)


def test_query_and_render(monkeypatch):
    subject = signed()
    event = receipt(subject)
    calls = []
    class Client:
        def __init__(self, relay, **kwargs):
            self.relay = relay
        async def query(self, filters):
            calls.append((self.relay, filters))
            if filters["kinds"] == [1418]:
                assert filters["#e"] == [subject.id]
                if self.relay == "wss://two.example":
                    raise TimeoutError()
                return [event]
            return [] if filters["kinds"] == [0] else [subject]
    monkeypatch.setattr(openetr, "RelayClient", Client)
    monkeypatch.setattr("app.zaps.public_relay", lambda url: url)
    history = asyncio.run(openetr.query_openetr_history(DIGEST, ["wss://one.example", "wss://two.example"]))
    graph = history["candidate_graphs"][0]
    assert len(graph["witnesses"]) == 1
    assert graph["witness_warnings"]
    assert history["verification"]["aggregate_state"] == "anchored"
    assert history["verification"]["evidence"] == [subject.data(), subject.data()]
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
    graph["witnesses"][0]["sources"] = ["<script>bad</script>"]
    html = env.get_template("_openetr_witnesses.html").render(graph=graph, _=lambda s: s)
    assert "Witness events" in html and event.id in html
    assert "&lt;script&gt;" in html and "<script>bad" not in html
    assert "have not been independently assessed" in html


def test_no_witness_panel_without_receipts():
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
    assert not env.get_template("_openetr_witnesses.html").render(graph={}, _=lambda s: s).strip()
