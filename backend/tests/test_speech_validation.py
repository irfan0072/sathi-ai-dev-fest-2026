"""Regression tests for speech input validation (judge audit finding 2).

The interpreter is a parser that runs after a provider transcribes audio. It must never turn
an approximate, conflicting, hedged or unvalidated transcript into an exact amount.
"""

from __future__ import annotations

import math

import pytest
from app.callcenter.interpret import MISSING_CONFIDENCE_POLICY, clean_confidence, interpret
from app.main import app
from app.txn.service import TxnCheckService
from app.voice import router as voice_router
from app.voice.providers import SimulatedVoiceProvider
from app.voice.service import VoiceService
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.mark.parametrize("speech", [
    "approximately three thousand", "about 3000", "around tin hajar", "roughly 3k",
    "প্রায় তিন হাজার", "মোটামুটি তিন হাজার", "prai tin hajar", "i think three thousand",
    "less than three thousand", "3000 or so maybe",
])
def test_approximate_amounts_are_never_exact(speech):
    answer = interpret("", speech, 0.95)
    assert answer.kind == "unclear" and answer.reason == "approximate" and answer.digits == ""


@pytest.mark.parametrize("speech", [
    "three thousand or four thousand", "তিন হাজার বা চার হাজার", "tin hajar naki char hajar",
    "300 500", "3000 5000", "three thousand five thousand", "tin tin hajar", "twenty thirty",
    "3000, 5000", "between three and four thousand",
])
def test_conflicting_amounts_are_never_summed_or_merged(speech):
    answer = interpret("", speech, 0.95)
    assert answer.kind == "unclear" and answer.digits == ""


@pytest.mark.parametrize("bad", [None, "", "  ", "nan", "inf", "-inf", "abc", "1.5", "-0.1",
                                 float("nan"), float("inf"), -1, 1.0001, True, [0.9], {"c": 1}])
def test_missing_or_invalid_confidence_never_yields_an_exact_amount(bad):
    answer = interpret("", "তিন হাজার", bad)
    assert answer.kind == "unclear" and answer.digits == ""
    assert answer.confidence is None or math.isfinite(answer.confidence)
    assert answer.reason in ("confidence_missing", "invalid_confidence")
    # An invalid confidence is reported as invalid, and the missing policy is explicit.
    expected = "confidence_missing" if bad in (None, "", "  ") else "invalid_confidence"
    assert answer.reason == expected
    assert MISSING_CONFIDENCE_POLICY == "unclear"


@pytest.mark.parametrize(("value", "status"), [
    (0.9, "ok"), ("0.9", "ok"), (0, "ok"), (1, "ok"), (" 0.75 ", "ok"), (None, "missing"),
    ("", "missing"), (float("nan"), "invalid"), ("NaN", "invalid"), (float("inf"), "invalid"),
    (2, "invalid"), (True, "invalid"), ([], "invalid"),
])
def test_clean_confidence(value, status):
    number, got = clean_confidence(value)
    assert got == status
    assert (number is not None) == (status == "ok")


@pytest.mark.parametrize("bad", [123, ["3000"], {"a": 1}, b"3000"])
def test_wrong_types_are_unclear_not_exceptions(bad):
    assert interpret(bad, None, None).kind == "unclear"
    assert interpret("", bad, 0.9).kind == "unclear"


def test_valid_paths_still_work():
    assert interpret("3000#", None, None).digits == "3000"            # keypad needs no confidence
    assert interpret("", "তিন হাজার পাঁচ শো", 0.9).digits == "3500"
    assert interpret("", "tin hajar pach sho", "0.88").digits == "3500"   # provider sends a string
    assert interpret("", "3,000 taka", 0.9).digits == "3000"
    assert interpret("", "2 lakh", 0.9).digits == "200000"
    assert interpret("", "আড়াই হাজার", 0.9).digits == "2500"
    assert interpret("", "0 3000", 0.9).digits == "03000"                # help signal, spoken


def test_silence_denial_keypad_help_and_duress_keep_their_meaning():
    assert interpret("", None, None).kind == "unclear"                   # empty: never denial
    assert interpret("#", None, None).kind == "unclear"                  # finish key alone
    assert interpret("*", None, None).kind == "denied"                   # explicit keypad denial
    assert interpret("*#", None, None).kind == "denied"
    assert interpret("", "ami kori nai", 0.9).kind == "denied"           # explicit denial phrase
    assert interpret("", "na", 0.9).kind == "unclear"                    # bare 'no' is not denial
    assert interpret("", "ami kori nai", None).kind == "unclear"         # no confidence: keypad
    assert interpret("03000", None, None).digits == "03000"              # duress keypad
    assert interpret("", "x" * 201, 0.9).reason == "too_long"


@pytest.fixture
def voice(durable_service):
    service = VoiceService(durable_service, SimulatedVoiceProvider())
    voice_router.set_voice_service(service)
    yield service
    voice_router.set_voice_service(None)


def _open_check(durable_service, voice, amount=500):
    check = TxnCheckService(durable_service).record_cashout("A_001", "U_001", amount)
    call = voice.start_check_call(check["check_id"], "A_001")
    return check, call["call_id"]


def _responses(durable_service, check_id):
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT interpreted, confidence FROM call_responses WHERE check_id = %s "
                    "ORDER BY response_id;", (check_id,))
        return cur.fetchall()


@pytest.mark.parametrize("confidence", ["nan", "inf", "7", "-1", "abc", None, float("nan"),
                                        float("inf"), True, [0.9]])
def test_bad_confidence_is_never_persisted_or_matched(durable_service, voice, confidence):
    """Webhook and IVR payloads reach the service as raw values (Twilio sends a string)."""
    check, call_id = _open_check(durable_service, voice, 3000)
    result = voice.handle_digits(call_id, "", "", speech="তিন হাজার", confidence=confidence)
    assert result.call_status == "in_progress"            # re-asked, not accepted
    rows = _responses(durable_service, check["check_id"])
    assert [r[0] for r in rows] == ["unclear"]
    assert all(conf is None for _, conf in rows)          # nothing invented, nothing non-finite
    assert TxnCheckService(durable_service).get(check["check_id"])["status"] != "verified"


def test_wrong_exact_amount_is_not_accepted_and_valid_speech_is(durable_service, voice):
    check, call_id = _open_check(durable_service, voice, 3000)
    voice.handle_digits(call_id, "", "", speech="approximately three thousand", confidence=0.95)
    voice.handle_digits(call_id, "", "", speech="three thousand five thousand", confidence=0.95)
    task = TxnCheckService(durable_service).get(check["check_id"])
    assert task["status"] == "manual_review"                # two unreadable answers -> a person
    check2, call2 = _open_check(durable_service, voice, 3000)
    voice.handle_digits(call2, "", "", speech="তিন হাজার", confidence=0.93)
    assert TxnCheckService(durable_service).get(check2["check_id"])["status"] == "verified"


def test_non_text_provider_values_do_not_crash_or_count_as_silence(durable_service, voice):
    check, call_id = _open_check(durable_service, voice, 500)
    result = voice.handle_digits(call_id, ["5", "0", "0"], "", speech=None, confidence=0.9)
    assert result.call_status == "in_progress"
    result = voice.handle_digits(call_id, "", "", speech={"text": "500"}, confidence=0.9,
                                 no_input=True)
    assert result.call_status in ("unclear", "in_progress")
    rows = _responses(durable_service, check["check_id"])
    assert rows and all(r[0] == "unclear" for r in rows)


def test_silence_is_still_not_denial(durable_service, voice):
    check, call_id = _open_check(durable_service, voice, 500)
    voice.handle_digits(call_id, "", "", no_input=True)
    assert [r[0] for r in _responses(durable_service, check["check_id"])] == ["no_input"]
    assert TxnCheckService(durable_service).get(check["check_id"])["status"] == "calling"


def test_simulated_answer_endpoint_rejects_non_finite_confidence(voice, durable_service):
    from tests.conftest import create_test_token  # noqa: PLC0415

    check, call_id = _open_check(durable_service, voice, 500)
    headers = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}",
               "Content-Type": "application/json"}
    for body in ('{"digits":"","speech":"500","confidence":NaN}',
                 '{"digits":"","speech":"500","confidence":1.5}',
                 '{"digits":"","speech":"500","confidence":Infinity}'):
        res = client.post(f"/api/v1/voice/calls/{call_id}/simulated-answer", headers=headers,
                          content=body)
        assert res.status_code == 422, (body, res.text)
    assert _responses(durable_service, check["check_id"]) == []


def test_voice_config_states_the_real_speech_capability(durable_service):
    from tests.conftest import create_test_token  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
    body = client.get("/api/v1/voice/config", headers=headers).json()
    speech = body["speech_input"]
    assert speech["validated_dialects"] == []
    assert speech["asr_model"].startswith("none")
    assert "unvalidated" in speech["validation_status"]
    assert "never invent" in speech["missing_confidence_policy"]
