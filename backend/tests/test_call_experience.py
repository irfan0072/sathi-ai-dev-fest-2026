"""Human-friendly calls: silence is not denial, key 9 reaches a person, key 8 switches
language, Banglish and Bangla spoken amounts are understood."""

from __future__ import annotations

import pytest
from app.callcenter.interpret import interpret
from app.callcenter.service import CallCenterService
from app.main import app
from app.mandates.service import MandateService
from app.notify import router as notify_router
from app.notify.service import NotificationService, SimulatedSmsProvider
from app.voice import router as voice_router
from app.voice import scripts
from app.voice.providers import SimulatedVoiceProvider
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}
POLICY = {"max_auto_attempts": 3, "retry_delay_seconds": 60, "ring_timeout_seconds": 45,
          "unclear_confidence": 0.6}


@pytest.fixture(autouse=True)
def services(durable_service: MandateService, monkeypatch):
    monkeypatch.setattr(CallCenterService, "policy", lambda self: dict(POLICY))
    voice = VoiceService(durable_service, SimulatedVoiceProvider())
    voice_router.set_voice_service(voice)
    notify_router.set_notification_service(
        NotificationService(durable_service.get_connection, SimulatedSmsProvider(), {}))
    yield voice
    voice_router.set_voice_service(None)
    notify_router.set_notification_service(None)


def _start(amount=3000) -> str:
    res = client.post("/api/v1/cashouts", headers=AGENT,
                      json={"user_id": "U_001", "amount": amount})
    assert res.status_code == 201
    return client.get("/api/v1/voice/incoming", headers=CUSTOMER).json()["calls"][0]["call_id"]


def _say(call_id: str, **body) -> dict:
    res = client.post(f"/api/v1/voice/calls/{call_id}/simulated-answer", headers=CUSTOMER,
                      json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _task(service: MandateService) -> tuple:
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT t.status, t.manual_reason, c.status, c.case_id FROM call_tasks t "
                    "JOIN txn_checks c USING (check_id);")
        return cur.fetchone()


def test_silence_reprompts_then_schedules_retry_never_denial(durable_service):
    call = _start()
    first = _say(call, no_input=True)
    assert first["call_ended"] is False and first["spoken"] == [scripts.line("bn", "no_input")]
    second = _say(call, no_input=True)
    assert second["call_ended"] is True
    task_status, _reason, check_status, case_id = _task(durable_service)
    assert task_status == "retry_scheduled" and check_status == "no_answer" and case_id is None


def test_key_nine_reaches_a_person(durable_service):
    out = _say(_start(), digits="9")
    assert out["call_ended"] and out["spoken"] == [scripts.line("bn", "handoff")]
    assert _task(durable_service)[:3] == ("needs_manual", "customer_requested_human",
                                         "manual_review")


def test_key_eight_switches_to_english_and_remembers(durable_service):
    call = _start(2000)
    out = _say(call, digits="8")
    assert out["call_ended"] is False and out["spoken"][0].startswith("Hello, this is Sathi")
    done = _say(call, digits="2000")
    assert done["spoken"] == [scripts.line("en", "close")]
    pref = client.get("/api/v1/me/language", headers=CUSTOMER).json()
    assert pref["language"] == "en" and pref["source"] == "call_keypad"


def test_banglish_spoken_amount_verifies(durable_service):
    _say(_start(2500), digits="", speech="arai hajar taka peyechi", confidence=0.9)
    assert _task(durable_service)[2] == "verified"


def test_bare_no_is_unclear_not_denial(durable_service):
    call = _start(1500)
    _say(call, digits="", speech="na", confidence=0.9)
    task_status, _reason, check_status, case_id = _task(durable_service)
    assert check_status == "calling" and case_id is None


def test_twilio_timeout_is_no_input(durable_service, services):
    call = _start()
    result = services.handle_digits(call, "", "https://x/gather", no_input=True)
    assert result.call_status == "in_progress"
    assert 'language="bn-IN"' in result.twiml


def test_same_closing_for_every_outcome_per_language():
    for lang in ("bn", "en", "banglish"):
        assert scripts.line(lang, "close")
        for key in ("check_prompt", "retry", "unclear", "no_input", "handoff"):
            text = scripts.line(lang, key)
            assert "PIN" not in text or "never" in text.lower() or "কখনো" in text \
                or "চাইব না" in text
            assert "৳" not in text  # the call never says an amount


@pytest.mark.parametrize(("speech", "kind", "value"), [
    ("দেড় হাজার", "amount", "1500"), ("আড়াই হাজার টাকা", "amount", "2500"),
    ("সাড়ে তিন হাজার", "amount", "3500"), ("tin hajar pach sho", "amount", "3500"),
    ("der hajar", "amount", "1500"), ("3.5k taka", "amount", "3500"),
    ("ছয় হাজার", "amount", "6000"), ("ami 2000 taka peyechi", "amount", "2000"),
    ("ami kori nai", "denied", ""), ("আমি টাকা তুলিনি", "denied", ""),
    ("ki bolchen bujhi nai", "unclear", ""), ("na", "unclear", ""),
])
def test_bangla_and_banglish_amounts(speech, kind, value):
    answer = interpret("", speech, 0.9)
    assert (answer.kind, answer.digits) == (kind, value)
