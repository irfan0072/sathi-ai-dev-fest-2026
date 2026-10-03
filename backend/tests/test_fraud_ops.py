"""Bangladesh IVR adapter, SMS notifications, command center, case timeline, watchlist."""

from __future__ import annotations

import io
import json
import urllib.parse

import pytest
from app.main import app
from app.mandates.service import MandateService
from app.notify import router as notify_router
from app.notify.service import (
    AlphaSmsProvider,
    NotificationService,
    SimulatedSmsProvider,
    sms_provider_from_env,
)
from app.ops.router import case_priority
from app.voice import router as voice_router
from app.voice.providers import BdHttpIvrProvider, VoiceProviderError, provider_from_env
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}
ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}
SECRET = "webhook-secret-0123456789"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def outbox(durable_service: MandateService):
    service = NotificationService(durable_service.get_connection, SimulatedSmsProvider(), {})
    notify_router.set_notification_service(service)
    yield service
    notify_router.set_notification_service(None)


def _request(amount: int = 3000) -> str:
    res = client.post("/api/v1/mandates/request", headers=AGENT,
                      json={"user_id": "U_001", "agent_id": "A_001", "amount": amount})
    assert res.status_code == 201, res.text
    return res.json()["mandate_id"]


# ----------------------------------------------------------------- Bangladesh IVR adapter
def test_bd_ivr_requires_https_key_and_strong_secret():
    with pytest.raises(VoiceProviderError):
        BdHttpIvrProvider("http://gw.example", "k", SECRET)
    with pytest.raises(VoiceProviderError):
        BdHttpIvrProvider("https://gw.example", "k", "short")
    provider = provider_from_env({"SATHI_VOICE_PROVIDER": "bd_http_ivr",
                                  "SATHI_BD_IVR_BASE_URL": "https://gw.example",
                                  "SATHI_BD_IVR_API_KEY": "k",
                                  "SATHI_BD_IVR_WEBHOOK_SECRET": SECRET})
    assert provider.name == "bd_http_ivr" and provider.language == "bn-BD"


def test_bd_ivr_full_call_with_signed_events(durable_service: MandateService, outbox):
    sent = []

    def opener(request, timeout):
        sent.append((request.full_url, dict(request.headers), json.loads(request.data)))
        return _Resp(b'{"call_id": "BD-1"}')

    base = "https://sathi-api.example.com"
    provider = BdHttpIvrProvider("https://gw.example/v1", "key", SECRET, opener=opener)
    voice_router.set_voice_service(
        VoiceService(durable_service, provider, base, {"U_001": "+8801712345678"}))
    try:
        mandate_id = _request()
        placed = client.post(f"/api/v1/mandates/{mandate_id}/call", headers=AGENT).json()
        assert placed["provider"] == "bd_http_ivr" and placed["to"].endswith("678")
        url, headers, body = sent[0]
        assert url == "https://gw.example/v1/calls"
        assert headers["Authorization"] == "Bearer key"
        assert body["gather"]["finish_on_key"] == "#" and "3000" not in json.dumps(body)
        path = body["callback_url"][len(base):]

        def post(event):
            raw = json.dumps(event).encode()
            return client.post(path, content=raw,
                               headers={"X-Sathi-Signature": provider.sign(raw),
                                        "Content-Type": "application/json"})

        assert client.post(path, content=b'{"event":"answered"}',
                           headers={"X-Sathi-Signature": "bad"}).status_code == 403
        answered = post({"event": "answered"}).json()
        assert answered["action"] == "gather" and answered["language"] == "bn-BD"
        retry = post({"event": "digits", "digits": "2500"}).json()
        assert retry["action"] == "gather"
        done = post({"event": "digits", "digits": "3000#"}).json()
        assert done["action"] == "hangup"
        assert durable_service.mandates.get(mandate_id).status == "verified"
        forged = path.split("?t=")[0] + "?t=forged"
        raw = b'{"event":"answered"}'
        assert client.post(forged, content=raw,
                           headers={"X-Sathi-Signature": provider.sign(raw)}).status_code == 403
    finally:
        voice_router.set_voice_service(None)


def test_missed_call_sends_follow_up_sms(durable_service: MandateService, outbox):
    provider = BdHttpIvrProvider("https://gw.example", "key", SECRET,
                                 opener=lambda *a, **k: _Resp(b'{"id": "X"}'))
    base = "https://api.example.com"
    service = VoiceService(durable_service, provider, base, {"U_001": "+8801712345678"})
    voice_router.set_voice_service(service)
    try:
        mandate_id = _request()
        call = service.start_call(mandate_id, "A_001")
        events = f"/api/v1/voice/ivr/{call['call_id']}/events?t=wrong-token"
        raw = json.dumps({"event": "status", "status": "no-answer"}).encode()
        assert client.post(events, content=raw,
                           headers={"X-Sathi-Signature": provider.sign(raw)}).status_code == 403
        voice_router._after_status(service, call["call_id"],
                                   service.provider_status(call["call_id"], "no-answer"))
        items = client.get("/api/v1/notifications", headers=CUSTOMER).json()["items"]
        assert items[0]["template"] == "verification_call_missed"
        assert "৩" not in items[0]["body"]  # never reveals the requested amount
    finally:
        voice_router.set_voice_service(None)


# ----------------------------------------------------------------- SMS notifications
def test_alpha_sms_request_and_error_mapping():
    seen = []

    def ok(request, timeout):
        seen.append(urllib.parse.parse_qs(request.data.decode()))
        return _Resp(b'{"error":0,"msg":"ok","data":{"request_id":42}}')

    result = AlphaSmsProvider("api-key", "SATHI", opener=ok).send("+8801712345678", "msg")
    assert result.status == "sent" and result.provider_ref == "42"
    assert seen[0]["to"] == ["8801712345678"] and seen[0]["sender_id"] == ["SATHI"]
    bad = AlphaSmsProvider("k", opener=lambda *a, **k: _Resp(b'{"error":417}')).send("+880", "m")
    assert bad.status == "failed" and "417" in bad.error
    with pytest.raises(ValueError):
        AlphaSmsProvider("")
    assert sms_provider_from_env({}).name == "simulated"


def test_redeem_sends_one_receipt_sms(durable_service: MandateService, outbox):
    mandate_id = _request(2000)
    durable_service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2000)
    code = client.post(f"/api/v1/mandates/{mandate_id}/issue-code", headers=AGENT).json()["code"]
    assert client.post(f"/api/v1/mandates/{mandate_id}/redeem", headers=AGENT,
                       json={"code": code}).status_code == 200
    items = client.get("/api/v1/notifications", headers=CUSTOMER).json()["items"]
    receipt = [i for i in items if i["template"] == "cashout_receipt"]
    assert len(receipt) == 1 and "২,০০০" in receipt[0]["body"]
    again = outbox.notify("U_001", "cashout_receipt", mandate_id=mandate_id, amount=1, fee=0)
    assert again["duplicate"] is True
    other = {"Authorization": f"Bearer {create_test_token('U_002', 'customer_channel')}"}
    assert client.get("/api/v1/notifications", headers=other).json()["items"] == []
    assert client.get("/api/v1/notifications", headers=AGENT).status_code == 403


# ----------------------------------------------------------------- fraud operations
def test_priority_table():
    assert case_priority("duress_signal") == ("urgent", 15)
    assert case_priority("unknown")[0] == "normal"


def test_overview_and_prioritized_cases(durable_service: MandateService):
    mandate_id = _request()
    durable_service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1)
    durable_service.create_case(mandate_id, "A_001", "duration_test", {})
    durable_service.create_case(None, "A_001", "duress_signal", {"priority": "urgent"})
    overview = client.get("/api/v1/ops/overview", headers=ANALYST).json()
    assert overview["totals"]["mandates"] >= 1
    assert overview["cases"]["urgent"] >= 1
    assert overview["agents"][0]["agent_id"] == "A_001"
    assert overview["events"]
    cases = client.get("/api/v1/ops/cases", headers=ANALYST).json()["cases"]
    assert cases[0]["priority"] == "urgent"
    assert client.get("/api/v1/ops/overview", headers=AGENT).status_code == 403


def test_case_timeline_orders_events(durable_service: MandateService):
    mandate_id = _request()
    durable_service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=10)
    case_id = [c for c in durable_service.cases if c["reason"] == "stated_amount_mismatch"][0][
        "case_id"]
    events = client.get(f"/api/v1/cases/{case_id}/timeline", headers=ANALYST).json()["events"]
    labels = [e["label"] for e in events]
    assert "mandate_requested" in labels and any(lbl.startswith("Case opened") for lbl in labels)
    assert [e["at"] for e in events] == sorted(e["at"] for e in events)
    assert client.get("/api/v1/cases/999999/timeline", headers=ANALYST).status_code == 404


def test_watchlist_forces_call_and_is_audited(durable_service: MandateService):
    res = client.put("/api/v1/watchlist/A_001", headers=ANALYST,
                     json={"reason": "Two cash-gap reports this week"})
    assert res.status_code == 200 and res.json()["watchlisted"] is True
    assert client.put("/api/v1/watchlist/A_404", headers=ANALYST,
                      json={"reason": "x" * 5}).status_code == 404
    assert client.put("/api/v1/watchlist/A_001", headers=AGENT,
                      json={"reason": "self"}).status_code == 403
    body = client.post("/api/v1/mandates/request", headers=AGENT,
                       json={"user_id": "U_001", "agent_id": "A_001", "amount": 500}).json()
    assert body["risk"]["step_up"] in ("call_required", "call_and_review")
    listed = client.get("/api/v1/watchlist", headers=ANALYST).json()["agents"]
    assert listed[0]["agent_id"] == "A_001"
    assert client.delete("/api/v1/watchlist/A_001", headers=ANALYST).json()["removed"] is True
    actions = [a["action"] for a in durable_service.audit_log]
    assert "agent_watchlisted" in actions and "agent_unwatchlisted" in actions
