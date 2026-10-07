"""Feature-phone voice/keypad path through the provider boundary.

A fake signed provider stands in for a telephony provider: requests reach the real webhook
routes, signature check, token check, service, persistence and TwiML builder. Nothing is
dialled. These tests are local simulation, not proof of a real feature-phone connection.
"""

from __future__ import annotations

import urllib.parse

import pytest
from app.analytics.router import set_analytics_service
from app.analytics.service import AnalyticsService
from app.callcenter.service import CallCenterService
from app.main import app
from app.mandates.router import set_mandate_service
from app.txn.service import TxnCheckService
from app.voice import router as voice_router
from app.voice.providers import PlacedCall
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.artifact_fixture import write_test_bundle
from tests.conftest import create_test_token

client = TestClient(app)
BASE = "https://api.example.test"
FORM = {"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": "ok"}
ADMIN = {"Authorization": f"Bearer {create_test_token('admin_777', 'super_admin')}"}
SUP = {"Authorization": f"Bearer {create_test_token('supervisor_777', 'supervisor')}"}
POLICY = {"max_auto_attempts": 3, "retry_delay_seconds": 60, "ring_timeout_seconds": 45,
          "unclear_confidence": 0.6}


class SignedProvider:
    """Accepts a webhook only with signature 'ok'; remembers the answer URL (with its token)."""

    name = "twilio"

    def __init__(self) -> None:
        self.answer_urls: list[str] = []

    def place_call(self, to_number, answer_url, status_url) -> PlacedCall:
        self.answer_urls.append(answer_url)
        return PlacedCall(provider_call_sid=f"CA{len(self.answer_urls):032d}", status="queued")

    def validate_request(self, url, params, signature) -> bool:
        return signature == "ok"


@pytest.fixture
def env(durable_service, monkeypatch, tmp_path):
    set_mandate_service(durable_service)
    set_analytics_service(AnalyticsService(mandate_service=durable_service,
                                           artifact_dir=write_test_bundle(tmp_path / "b")))
    provider = SignedProvider()
    phones = {f"U_00{i}": f"+88017000000{i}" for i in range(1, 3)} | {"U_001": "+8801700000001"}

    def build():
        service = VoiceService(durable_service, provider, public_base_url=BASE, phone_book=phones)
        voice_router.set_voice_service(service)
        return service

    monkeypatch.setattr(CallCenterService, "policy", lambda self: dict(POLICY))
    yield durable_service, provider, build
    voice_router.set_voice_service(None)
    set_analytics_service(None)


def _start(env, amount, user="U_001"):
    db, provider, build = env
    service = build()
    check = TxnCheckService(db).record_cashout("A_001", user, amount)
    call = service.start_check_call(check["check_id"], "A_001")
    url = provider.answer_urls[-1]
    token = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["t"][0]
    return check, call["call_id"], token


def _gather(call_id, token, **fields):
    body = urllib.parse.urlencode(fields)
    return client.post(f"/api/v1/voice/calls/{call_id}/gather?t={token}", content=body,
                       headers=FORM)


def _state(db, check_id):
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT c.status, c.outcome, c.case_id, t.priority, t.followup_status "
                    "FROM txn_checks c JOIN call_tasks t USING (check_id) "
                    "WHERE c.check_id = %s;", (check_id,))
        return cur.fetchone()


def _mode(db, call_id):
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT input_mode, speech_unusable_count FROM voice_calls "
                    "WHERE call_id = %s;", (call_id,))
        return cur.fetchone()


def _answer_twiml(env, call_id, token):
    return client.post(f"/api/v1/voice/calls/{call_id}/answer?t={token}", content="",
                       headers=FORM).text


# ------------------------------------------------------------------ keypad-only is real
def test_first_prompt_accepts_speech_and_keypad(env):
    check, call_id, token = _start(env, 3000)
    xml = _answer_twiml(env, call_id, token)
    assert 'input="dtmf speech"' in xml and "3000" not in xml


@pytest.mark.parametrize("fields", [
    {"SpeechResult": "umm ami bujhi nai", "Confidence": "0.3"},      # low confidence
    {"SpeechResult": "তিন হাজার"},                                    # missing confidence
    {"SpeechResult": "approximately three thousand", "Confidence": "0.95"},
    {"SpeechResult": "তিন হাজার", "Confidence": "nan"},               # invalid confidence
])
def test_unusable_speech_switches_the_next_prompt_to_dtmf_only(env, fields):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    xml = _gather(call_id, token, **fields).text
    assert 'input="dtmf"' in xml and "speech" not in xml.replace("SpeechResult", "")
    assert _mode(db, call_id) == ("dtmf_only", 1)
    assert _state(db, check["check_id"])[:2] == ("calling", None)    # nothing was concluded


def test_speech_timeout_also_switches_to_dtmf_only_and_survives_restart(env):
    db, provider, build = env
    check, call_id, token = _start(env, 3000)
    xml = _gather(call_id, token).text                               # empty callback = timeout
    assert 'input="dtmf"' in xml and _mode(db, call_id)[0] == "dtmf_only"
    build()                                                          # "restart": new service object
    assert 'input="dtmf"' in _answer_twiml(env, call_id, token)
    assert 'input="dtmf"' in _gather(call_id, token, Digits="2000").text   # mismatch retry too
    assert _mode(db, call_id)[0] == "dtmf_only"


def test_keypad_amount_after_failed_speech_matches(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    _gather(call_id, token, SpeechResult="mumble", Confidence="0.2")
    xml = _gather(call_id, token, Digits="3000").text
    assert "<Hangup/>" in xml
    assert _state(db, check["check_id"])[:2] == ("verified", "match")


# ------------------------------------------------------------------ empty is never denial
def test_signed_empty_callback_without_finishedonkey_is_not_a_denial(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    response = _gather(call_id, token)  # no Digits, SpeechResult or FinishedOnKey
    assert response.status_code == 200
    state = _state(db, check["check_id"])
    assert state[0] not in ("suspicious", "verified") and state[2] is None   # no case
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT interpreted FROM call_responses WHERE check_id = %s;",
                    (check["check_id"],))
        assert [r[0] for r in cur.fetchall()] == ["no_input"]


def test_hash_alone_is_reprompted_not_denied(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    _gather(call_id, token, FinishedOnKey="#")                       # finish key, nothing typed
    assert _state(db, check["check_id"])[2] is None


def test_unsigned_callback_is_refused(env):
    check, call_id, token = _start(env, 3000)
    bad = client.post(f"/api/v1/voice/calls/{call_id}/gather?t={token}", content="Digits=3000",
                      headers={**FORM, "X-Twilio-Signature": "forged"})
    assert bad.status_code == 403
    assert client.post(f"/api/v1/voice/calls/{call_id}/gather?t=wrong", content="Digits=3000",
                       headers=FORM).status_code == 403


def test_explicit_star_is_the_denial(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    _gather(call_id, token, Digits="*")
    state = _state(db, check["check_id"])
    assert state[:2] == ("suspicious", "denied") and state[4] == "required"


# ------------------------------------------------------------------ mismatch, urgency, gate
def test_two_mismatches_open_a_case_and_the_clearance_gate_holds(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    for _ in range(2):
        _gather(call_id, token, Digits="2000")
    status, outcome, case_id, priority, followup = _state(db, check["check_id"])
    assert (status, outcome, followup, priority) == ("suspicious", "mismatch", "required", "high")
    refused = client.post(f"/api/v1/cases/{case_id}/decision", headers=ADMIN,
                          json={"decision": "approved", "note": "x"})
    assert refused.status_code == 409


def test_secret_help_is_urgent_and_sorts_above_an_ordinary_mismatch(env):
    db = env[0]
    mismatch, call_a, token_a = _start(env, 3000, "U_001")
    for _ in range(2):
        _gather(call_a, token_a, Digits="2000")
    help_check, call_b, token_b = _start(env, 700, "U_002")
    xml = _gather(call_b, token_b, Digits="0700").text
    assert "700" not in xml and "duress" not in xml.lower()          # neutral ending
    status, outcome, case_id, priority, followup = _state(db, help_check["check_id"])
    assert (status, outcome, priority, followup) == ("suspicious", "duress", "urgent", "required")
    queue = client.get("/api/v1/callcenter/queue?scope=followup", headers=SUP).json()["items"]
    assert [i["priority"] for i in queue][:2] == ["urgent", "high"]
    assert queue[0]["check_id"] == help_check["check_id"]
    # Urgency survives later lifecycle updates (claim, resolution hooks, retries).
    CallCenterService(db).on_resolved(help_check["check_id"], "suspicious")
    CallCenterService(db).claim_followup(queue[0]["task_id"], "supervisor_777")
    assert _state(db, help_check["check_id"])[3] == "urgent"
    refused = client.post(f"/api/v1/cases/{case_id}/decision", headers=ADMIN,
                          json={"decision": "approved", "note": "x"})
    assert refused.status_code == 409


# ------------------------------------------------------------------ duplicates and lateness
def test_duplicate_and_late_callbacks_do_not_change_a_terminal_result(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    _gather(call_id, token, Digits="3000")
    before = _state(db, check["check_id"])
    for fields in ({"Digits": "3000"}, {"Digits": "*"}, {"Digits": "0300"}, {}):
        assert _gather(call_id, token, **fields).status_code == 200
    assert _state(db, check["check_id"]) == before
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cases;")
        assert cur.fetchone()[0] == 0


def test_provider_disconnect_before_an_answer_schedules_a_retry_not_a_result(env):
    db = env[0]
    check, call_id, token = _start(env, 3000)
    status_url = f"/api/v1/voice/calls/{call_id}/status?t={token}"
    for _ in range(2):                                               # duplicate status callback
        assert client.post(status_url, content="CallStatus=no-answer", headers=FORM
                           ).status_code == 204
    state = _state(db, check["check_id"])
    assert state[0] == "no_answer" and state[2] is None
    task = CallCenterService(db).detail(
        CallCenterService(db).queue("retrying", "x")["items"][0]["task_id"])
    assert task["auto_attempts"] == 1 and task["status"] == "retry_scheduled"


def test_no_prompt_asks_for_a_pin_or_otp():
    from app.voice import scripts

    for language in ("bn", "banglish", "en"):
        for key, text in scripts.SCRIPTS[language].items():
            lowered = text.lower()
            if any(word in lowered for word in ("pin", "otp", "পিন", "ওটিপি")):
                assert any(word in lowered for word in ("never", "কখনো", "চাইব না", "বলবেন না")), \
                key


def test_bd_ivr_gateway_is_told_to_collect_keypad_only_after_unusable_speech(durable_service):
    """Provisional, vendor-unconfirmed contract field: gather.input == 'dtmf'."""
    import hashlib
    import hmac
    import json

    from app.voice.providers import BdHttpIvrProvider

    provider = BdHttpIvrProvider("https://ivr.example.test", "key", "s" * 20)
    captured = {}
    provider.place_call = lambda to, answer_url, status_url: (
        captured.setdefault("url", answer_url) and PlacedCall("X1", "queued"))
    service = VoiceService(durable_service, provider, public_base_url=BASE,
                           phone_book={"U_001": "+8801700000001"})
    voice_router.set_voice_service(service)
    try:
        check = TxnCheckService(durable_service).record_cashout("A_001", "U_001", 3000)
        call = service.start_check_call(check["check_id"], "A_001")
        path = urllib.parse.urlparse(captured["url"])

        def event(body):
            raw = json.dumps(body).encode()
            sig = hmac.new(b"s" * 20, raw, hashlib.sha256).hexdigest()
            return client.post(f"{path.path}?{path.query}", content=raw,
                               headers={"X-Sathi-Signature": sig}).json()

        first = event({"event": "answered"})
        assert "input" not in first["gather"]
        retry = event({"event": "digits", "digits": "", "speech": "mumble", "confidence": 0.2})
        assert retry["action"] == "gather" and retry["gather"]["input"] == "dtmf"
        assert call["call_id"]
    finally:
        voice_router.set_voice_service(None)
