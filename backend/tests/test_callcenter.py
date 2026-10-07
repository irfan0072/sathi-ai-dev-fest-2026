"""Call management: retries, ignored after N misses, unclear answers to a supervisor."""

from __future__ import annotations

import pytest
from app.callcenter import worker as call_worker
from app.callcenter.interpret import interpret
from app.callcenter.service import CallCenterService
from app.main import app
from app.mandates.service import MandateService
from app.notify import router as notify_router
from app.notify.service import NotificationService, SimulatedSmsProvider
from app.voice import router as voice_router
from app.voice.providers import SimulatedVoiceProvider
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}
SUP = {"Authorization": f"Bearer {create_test_token('supervisor_777', 'supervisor')}"}
NADIA = {"Authorization": f"Bearer {create_test_token('sup_nadia', 'supervisor')}"}
ADMIN = {"Authorization": f"Bearer {create_test_token('admin_777', 'super_admin')}"}
POLICY = {"max_auto_attempts": 3, "retry_delay_seconds": 60, "ring_timeout_seconds": 45,
          "unclear_confidence": 0.6}


@pytest.fixture(autouse=True)
def services(durable_service: MandateService):
    voice = VoiceService(durable_service, SimulatedVoiceProvider())
    voice_router.set_voice_service(voice)
    notify_router.set_notification_service(
        NotificationService(durable_service.get_connection, SimulatedSmsProvider(), {}))
    yield voice
    voice_router.set_voice_service(None)
    notify_router.set_notification_service(None)


def _cashout(amount=3000) -> dict:
    res = client.post("/api/v1/cashouts", headers=AGENT,
                      json={"user_id": "U_001", "amount": amount})
    assert res.status_code == 201, res.text
    return res.json()


def _task(durable_service, txn_id: int) -> dict:
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT t.task_id FROM call_tasks t JOIN txn_checks c USING (check_id) "
                    "WHERE c.txn_id = %s;", (txn_id,))
        task_id = cur.fetchone()[0]
    return CallCenterService(durable_service, policy=lambda: POLICY).detail(task_id)


def _live_call(durable_service, txn_id: int) -> str:
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT v.call_id FROM voice_calls v JOIN txn_checks c USING (check_id) "
                    "WHERE c.txn_id = %s AND v.status IN ('queued','ringing','in_progress');",
                    (txn_id,))
        row = cur.fetchone()
    return str(row[0]) if row else ""


def _answer(call_id: str, **body) -> None:
    res = client.post(f"/api/v1/voice/calls/{call_id}/simulated-answer", headers=CUSTOMER,
                      json=body)
    assert res.status_code == 200, res.text


def _make_due(durable_service) -> None:
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE call_tasks SET next_attempt_at = now() - interval '1 second' "
                    "WHERE status = 'retry_scheduled';")
        conn.commit()


def _patch_policy(monkeypatch):
    monkeypatch.setattr(CallCenterService, "policy", lambda self: dict(POLICY))


def test_cashout_creates_call_task(durable_service):
    out = _cashout()
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "auto" and task["auto_attempts"] == 1
    assert len(task["calls"]) == 1


def test_missed_calls_retry_then_ignored(durable_service, services, monkeypatch):
    _patch_policy(monkeypatch)
    out = _cashout()
    center = CallCenterService(durable_service, policy=lambda: POLICY)
    for attempt in range(1, 4):
        services.provider_status(_live_call(durable_service, out["txn_id"]), "no-answer")
        task = _task(durable_service, out["txn_id"])
        if attempt < 3:
            assert task["status"] == "retry_scheduled", attempt
            assert task["next_attempt_at"]
            assert center.claim_due_retries() == []  # not due yet
            _make_due(durable_service)
            due = center.claim_due_retries()
            assert due == [task["check_id"]]
            services.start_check_call(due[0], "sathi-scheduler")
            assert _task(durable_service, out["txn_id"])["auto_attempts"] == attempt + 1
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "ignored" and task["resolution"] == "unreachable"
    assert task["check_status"] == "unreachable"
    assert [r["interpreted"] for r in task["responses"]] == ["no_answer"] * 3
    assert any(h["action"] == "call_task_ignored" for h in task["history"])


def test_ring_timeout_sweeper_marks_no_answer(durable_service, services, monkeypatch):
    _patch_policy(monkeypatch)
    out = _cashout()
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE voice_calls SET created_at = now() - interval '2 minutes';")
        conn.commit()
    monkeypatch.setattr(call_worker.Worker, "_services", lambda self: (
        durable_service, CallCenterService(durable_service, policy=lambda: POLICY), services))
    result = call_worker.Worker().tick()
    assert result["timeouts"] == 1
    assert _task(durable_service, out["txn_id"])["status"] == "retry_scheduled"


def test_abandoned_answered_call_times_out(durable_service, services, monkeypatch):
    """Customer answered, typed a wrong amount once, then left: the call must not stay live."""
    _patch_policy(monkeypatch)
    out = _cashout(3000)
    call = _live_call(durable_service, out["txn_id"])
    _answer(call, digits="2000")  # first mismatch: asked again, call stays in progress
    monkeypatch.setattr(call_worker.Worker, "_services", lambda self: (
        durable_service, CallCenterService(durable_service, policy=lambda: POLICY), services))
    assert call_worker.Worker().tick()["timeouts"] == 0  # still within the answer window
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE voice_calls SET updated_at = now() - interval '4 minutes';")
        conn.commit()
    assert call_worker.Worker().tick()["timeouts"] == 1
    assert _live_call(durable_service, out["txn_id"]) == ""
    assert _task(durable_service, out["txn_id"])["status"] == "retry_scheduled"


def test_unclear_answer_goes_to_manual_queue_and_supervisor_resolves(
        durable_service, monkeypatch):
    _patch_policy(monkeypatch)
    out = _cashout(3000)
    call = _live_call(durable_service, out["txn_id"])
    _answer(call, digits="", speech="umm ami bujhi nai", confidence=0.3)
    assert _task(durable_service, out["txn_id"])["status"] == "auto"  # asked again
    _answer(call, digits="ab")  # unreadable keys
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "needs_manual" and task["manual_reason"] == "unclear_response"
    assert task["check_status"] == "manual_review"
    assert [r["interpreted"] for r in task["responses"]] == ["unclear", "unclear"]
    assert task["responses"][0]["raw_input"] == "umm ami bujhi nai"

    pending = client.get("/api/v1/callcenter/queue?scope=pending", headers=SUP).json()
    assert [t["task_id"] for t in pending["items"]] == [task["task_id"]]
    assert client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/claim",
                       headers=SUP).status_code == 200
    taken = client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/claim", headers=NADIA)
    assert taken.status_code == 409
    assert client.get(f"/api/v1/callcenter/tasks/{task['task_id']}",
                      headers=NADIA).status_code == 404  # not hers, not pending
    assert client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/start",
                       headers=SUP).status_code == 200
    res = client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/outcome", headers=SUP, json={
        "result": "amount_mismatch", "stated_amount": 2500,
        "note": "Customer says she got 2500 only."})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved" and res.json()["resolution"] == "suspicious"

    task = _task(durable_service, out["txn_id"])
    assert task["case_id"] is not None and task["check_status"] == "suspicious"
    file = client.get(f"/api/v1/cases/{task['case_id']}/file", headers=SUP).json()
    assert file["evidence"]["channel"] == "supervisor call"
    assert file["notes_list"][0]["note_type"] == "call_log"
    assert file["assigned_to"] == "supervisor_777" and file["can_act"]
    assert task["responses"][-1]["channel"] == "manual"


def test_manual_confirm_with_matching_amount_verifies(durable_service, monkeypatch):
    _patch_policy(monkeypatch)
    out = _cashout(2000)
    task = _task(durable_service, out["txn_id"])
    assert client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/assign", headers=ADMIN,
                       json={"staff_id": "sup_nadia"}).status_code == 200
    mine = client.get("/api/v1/callcenter/queue?scope=mine", headers=NADIA).json()["items"]
    assert [t["task_id"] for t in mine] == [task["task_id"]]
    res = client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/outcome", headers=NADIA,
                      json={"result": "confirmed", "stated_amount": 2000})
    assert res.json()["resolution"] == "verified"
    assert _task(durable_service, out["txn_id"])["check_status"] == "verified"


def test_callback_reschedules(durable_service, monkeypatch):
    _patch_policy(monkeypatch)
    out = _cashout()
    task = _task(durable_service, out["txn_id"])
    client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/assign", headers=ADMIN,
                json={"staff_id": "supervisor_777"})
    res = client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/outcome", headers=SUP,
                      json={"result": "callback", "callback_minutes": 30,
                            "note": "Customer busy, call after 30 min"})
    assert res.status_code == 200
    assert res.json()["status"] == "retry_scheduled"
    assert res.json()["manual_reason"] == "customer_callback"


def test_admin_escalates_ignored_and_distributes(durable_service, services, monkeypatch):
    _patch_policy(monkeypatch)
    monkeypatch.setattr(CallCenterService, "policy", lambda self: {**POLICY,
                                                                   "max_auto_attempts": 1})
    out = _cashout()
    services.provider_status(_live_call(durable_service, out["txn_id"]), "no-answer")
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "ignored"
    ignored = client.get("/api/v1/callcenter/queue?scope=ignored", headers=ADMIN).json()
    assert task["task_id"] in [t["task_id"] for t in ignored["items"]]
    res = client.post(f"/api/v1/callcenter/tasks/{task['task_id']}/escalate", headers=ADMIN)
    assert res.status_code == 200 and res.json()["status"] == "needs_manual"
    dist = client.post("/api/v1/callcenter/distribute", headers=ADMIN).json()
    assert dist["total"] == 1
    stats = client.get("/api/v1/callcenter/stats", headers=ADMIN).json()
    assert stats["manual_active"] == 1 and stats["calls_24h"]["missed"] == 1


def test_clear_answer_resolves_task(durable_service):
    out = _cashout(1500)
    _answer(_live_call(durable_service, out["txn_id"]), digits="1500")
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "resolved" and task["resolution"] == "verified"
    assert task["responses"][0]["interpreted"] == "amount"


def test_speech_amount_is_understood(durable_service):
    out = _cashout(2500)
    _answer(_live_call(durable_service, out["txn_id"]), speech="দুই হাজার পাঁচ শ টাকা",
            confidence=0.91)
    task = _task(durable_service, out["txn_id"])
    assert task["resolution"] == "verified"


@pytest.mark.parametrize(("digits", "speech", "conf", "kind", "value"), [
    ("3000", None, None, "amount", "3000"),
    ("3000#", None, None, "amount", "3000"),
    ("*", None, None, "denied", ""),
    ("*#", None, None, "denied", ""),
    ("#", None, None, "unclear", ""),     # finish key alone is an empty answer, not a denial
    ("", None, None, "unclear", ""),      # nothing typed or said: never a denial
    ("*5", None, None, "unclear", ""),
    ("*12", None, None, "unclear", ""),
    ("0", None, None, "unclear", ""),
    ("123456789", None, None, "unclear", ""),
    ("", "three thousand five hundred", 0.9, "amount", "3500"),
    ("", "৩০০০", 0.8, "amount", "3000"),
    ("", "2 lakh", 0.8, "amount", "200000"),
    ("", "three thousand", 0.3, "unclear", ""),
    ("", "ki bolchen bujhi nai", 0.9, "unclear", ""),
    ("", "না, আমি করিনি", 0.9, "denied", ""),
    ("", "0 3000", 0.9, "amount", "03000"),
])
def test_interpret(digits, speech, conf, kind, value):
    answer = interpret(digits, speech, conf)
    assert answer.kind == kind and answer.digits == value


def test_simulator_behaviour_mix_is_realistic():
    names = [call_worker.behaviour_for(f"call-{i}") for i in range(4000)]
    share = {n: names.count(n) / len(names) for n in set(names)}
    assert 0.55 < share["confirm"] + share["speak_amount"] < 0.72
    assert 0.10 < share["no_answer"] < 0.20
    assert share["duress"] < 0.03
