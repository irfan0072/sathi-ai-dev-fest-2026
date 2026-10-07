"""Initial call-failure recovery and the safe independent follow-up queue.

Synthetic, local, deterministic: a fake provider fails on demand. Nothing here places a call
or sends an SMS. A failed placement must never strand a committed cash-out, never debit the
ledger a second time, and never place a duplicate call when the provider may have accepted
the first one.
"""

from __future__ import annotations

import pytest
from app.callcenter import worker as call_worker
from app.callcenter.service import CallCenterService
from app.main import app
from app.mandates.service import MandateService
from app.voice import router as voice_router
from app.voice.providers import PlacedCall, SimulatedVoiceProvider, VoiceProviderError
from app.voice.service import VoiceError, VoiceService
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


class FlakyProvider:
    """Behaves like the simulated provider but fails the next `fail` placements."""

    name = "simulated"

    def __init__(self, fail: int = 0, error: Exception | None = None) -> None:
        self.fail, self.error, self.placed = fail, error, 0
        self._ok = SimulatedVoiceProvider()

    def place_call(self, to_number, answer_url, status_url) -> PlacedCall:
        if self.fail > 0:
            self.fail -= 1
            raise self.error or VoiceProviderError("Provider is down.")
        self.placed += 1
        return self._ok.place_call(to_number, answer_url, status_url)

    def validate_request(self, url, params, signature) -> bool:
        return False


@pytest.fixture
def setup(durable_service: MandateService, monkeypatch, tmp_path):
    from app.analytics.router import set_analytics_service
    from app.analytics.service import AnalyticsService
    from app.mandates.router import set_mandate_service
    from tests.artifact_fixture import write_test_bundle

    set_mandate_service(durable_service)
    set_analytics_service(AnalyticsService(mandate_service=durable_service,
                                           artifact_dir=write_test_bundle(tmp_path / "bundle")))
    holder = {}

    def use(provider):
        service = VoiceService(durable_service, provider)
        voice_router.set_voice_service(service)
        holder["voice"] = service
        monkeypatch.setattr(call_worker.Worker, "_services", lambda self: (
            durable_service, CallCenterService(durable_service, policy=lambda: POLICY), service))
        return service

    monkeypatch.setattr(CallCenterService, "policy", lambda self: dict(POLICY))
    yield use
    voice_router.set_voice_service(None)
    set_analytics_service(None)


def _cashout(amount=3000):
    res = client.post("/api/v1/cashouts", headers=AGENT,
                      json={"user_id": "U_001", "amount": amount})
    assert res.status_code == 201, res.text
    return res.json()


def _task(db, txn_id):
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT t.task_id FROM call_tasks t JOIN txn_checks c USING (check_id) "
                    "WHERE c.txn_id = %s;", (txn_id,))
        task_id = cur.fetchone()[0]
    return CallCenterService(db, policy=lambda: POLICY).detail(task_id)


def _scalar(db, sql, params=()):
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def _make_due(db):
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE call_tasks SET next_attempt_at = now() - interval '1 second' "
                    "WHERE status = 'retry_scheduled';")
        conn.commit()


def _cash_out_rows(db):
    return _scalar(db, "SELECT count(*) FROM transactions WHERE txn_type = 'cash_out' "
                       "AND user_id = 'U_001';")


# ------------------------------------------------------------------ initial placement failure
def test_initial_placement_failure_is_retried_then_goes_to_a_person(durable_service, setup):
    provider = FlakyProvider(fail=99)
    setup(provider)
    out = _cashout(3000)
    assert out["check"] == "waiting"                      # the agent still sees a neutral state
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "retry_scheduled" and task["auto_attempts"] == 1
    assert task["placement_failures"] == 1 and "Provider is down" in task["last_placement_error"]
    assert task["check_status"] == "pending" and task["calls"][0]["status"] == "failed"

    for expected in (2, 3):
        _make_due(durable_service)
        assert call_worker.Worker().tick()["retries"] == 0
        task = _task(durable_service, out["txn_id"])
        assert task["auto_attempts"] == expected and task["placement_failures"] == expected

    assert task["status"] == "needs_manual" and task["manual_reason"] == "provider_failure"
    assert task["check_status"] == "manual_review" and task["priority"] == "high"
    assert any(h["action"] == "call_task_needs_manual" for h in task["history"])
    # Bounded: no further automatic attempt, no duplicate call rows beyond the budget.
    _make_due(durable_service)
    call_worker.Worker().tick()
    assert _task(durable_service, out["txn_id"])["auto_attempts"] == 3
    assert len(_task(durable_service, out["txn_id"])["calls"]) == 3
    # A delivery error never reverses or debits the ledger a second time.
    assert _cash_out_rows(durable_service) == 1
    pending = client.get("/api/v1/callcenter/queue?scope=pending", headers=SUP).json()
    assert [t["task_id"] for t in pending["items"]] == [task["task_id"]]


def test_provider_recovers_on_retry(durable_service, setup):
    provider = FlakyProvider(fail=1)
    setup(provider)
    out = _cashout(2000)
    assert _task(durable_service, out["txn_id"])["status"] == "retry_scheduled"
    _make_due(durable_service)
    assert call_worker.Worker().tick()["retries"] == 1
    task = _task(durable_service, out["txn_id"])
    assert (task["status"], task["auto_attempts"], task["check_status"]) == ("auto", 2, "calling")
    assert provider.placed == 1
    assert task["calls"][-1]["status"] in ("ringing", "queued")


def test_missing_registered_phone_is_recoverable_not_stranded(durable_service, monkeypatch):
    class Real(FlakyProvider):
        name = "twilio"

    service = VoiceService(durable_service, Real(), public_base_url="https://api.example.test")
    voice_router.set_voice_service(service)
    monkeypatch.setattr(CallCenterService, "policy", lambda self: dict(POLICY))
    try:
        out = _cashout(1000)
    finally:
        voice_router.set_voice_service(None)
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "retry_scheduled"
    assert "NO_REGISTERED_PHONE" in task["last_placement_error"]


def test_unexpected_provider_exception_is_contained_and_counted(durable_service, setup):
    setup(FlakyProvider(fail=99, error=RuntimeError("library bug")))
    out = _cashout(1500)
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "retry_scheduled" and task["calls"][0]["status"] == "failed"
    assert _scalar(durable_service, "SELECT count(*) FROM voice_calls WHERE status IN "
                                    "('queued','ringing','in_progress');") == 0


def test_uncertain_provider_acceptance_never_places_a_duplicate_call(durable_service, setup):
    provider = FlakyProvider(fail=1, error=VoiceProviderError("timed out", ambiguous=True))
    voice = setup(provider)
    out = _cashout(2500)
    task = _task(durable_service, out["txn_id"])
    # The first call may exist at the provider: it stays live and the task is not rescheduled.
    assert task["calls"][0]["status"] == "queued" and task["last_outcome"] == "placement_uncertain"
    assert task["status"] == "auto" and task["auto_attempts"] == 0
    check_id = task["check_id"]
    with pytest.raises(VoiceError) as blocked:
        voice.start_check_call(check_id, "sathi-scheduler")
    assert blocked.value.code == "CALL_IN_PROGRESS"
    assert provider.placed == 0 and len(_task(durable_service, out["txn_id"])["calls"]) == 1
    # No provider callback ever arrives: the ring timeout settles the live call and retries.
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE voice_calls SET created_at = now() - interval '2 minutes';")
        conn.commit()
    assert call_worker.Worker().tick()["timeouts"] == 1
    assert _task(durable_service, out["txn_id"])["status"] == "retry_scheduled"


def test_duplicate_provider_callbacks_do_not_double_count(durable_service, setup):
    voice = setup(FlakyProvider())
    out = _cashout(1000)
    task = _task(durable_service, out["txn_id"])
    call_id = task["calls"][0]["call_id"]
    for _ in range(3):
        voice.provider_status(call_id, "no-answer")
    task = _task(durable_service, out["txn_id"])
    assert task["status"] == "retry_scheduled" and task["auto_attempts"] == 1
    assert [r["interpreted"] for r in task["responses"]] == ["no_answer"]


def test_committed_check_with_no_call_is_reclaimed_after_a_crash(durable_service, setup):
    """The process died after committing the cash-out and before placing the call."""
    voice = setup(FlakyProvider())
    from app.txn.service import TxnCheckService

    check = TxnCheckService(durable_service).record_cashout("A_001", "U_001", 1200)
    center = CallCenterService(durable_service, policy=lambda: POLICY)
    assert center.claim_due_retries() == []                      # inside the lease
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE call_tasks SET updated_at = now() - interval '10 minutes';")
        conn.commit()
    assert center.claim_due_retries() == [check["check_id"]]
    assert center.claim_due_retries() == []                      # lease renewed: one claimer
    voice.start_check_call(check["check_id"], "sathi-scheduler")
    assert _task(durable_service, check["txn_id"])["calls"][0]["status"] in ("ringing", "queued")
    assert _cash_out_rows(durable_service) == 1


def test_crash_reclaim_with_every_attempt_used_goes_to_a_person(durable_service, setup):
    setup(FlakyProvider())
    from app.txn.service import TxnCheckService

    check = TxnCheckService(durable_service).record_cashout("A_001", "U_001", 1200)
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE call_tasks SET updated_at = now() - interval '10 minutes', "
                    "auto_attempts = 3;")
        conn.commit()
    assert CallCenterService(durable_service, policy=lambda: POLICY).claim_due_retries() == []
    task = _task(durable_service, check["txn_id"])
    assert task["status"] == "needs_manual" and task["manual_reason"] == "provider_failure"


def test_restart_between_ticks_keeps_the_retry_state(durable_service, setup):
    setup(FlakyProvider(fail=2))
    out = _cashout(900)
    _make_due(durable_service)
    call_worker.Worker().tick()                                    # "process 1"
    _make_due(durable_service)
    result = call_worker.Worker().tick()                           # "process 2" after a restart
    assert result["retries"] == 1
    assert _task(durable_service, out["txn_id"])["auto_attempts"] == 3


# ------------------------------------------------------------------ independent follow-up
def _mismatch_case(db, setup):
    voice = setup(FlakyProvider())
    out = _cashout(3000)
    call_id = _task(db, out["txn_id"])["calls"][0]["call_id"]
    for digits in ("2000", "2000"):
        voice.handle_digits(call_id, digits, "")
    task = _task(db, out["txn_id"])
    assert task["check_status"] == "suspicious" and task["case_id"]
    return out, task


def _decide(case_id, decision):
    return client.post(f"/api/v1/cases/{case_id}/decision", headers=ADMIN,
                       json={"decision": decision, "note": "synthetic test"})


def test_suspicious_check_requires_independent_follow_up_and_cannot_be_cleared(
        durable_service, setup):
    out, task = _mismatch_case(durable_service, setup)
    assert task["followup_status"] == "required" and task["priority"] == "high"
    refused = _decide(task["case_id"], "approved")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "INDEPENDENT_CONTACT_REQUIRED"
    assert _decide(task["case_id"], "escalated").status_code == 200   # escalation stays possible


def test_same_handset_contact_never_counts_as_independent(durable_service, setup):
    out, task = _mismatch_case(durable_service, setup)
    base = f"/api/v1/callcenter/tasks/{task['task_id']}"
    assert client.post(f"{base}/followup", headers=SUP,
                       json={"outcome": "attempted", "channel": "registered_number"}
                       ).json()["error"]["code"] == "CLAIM_FIRST"
    assert client.post(f"{base}/followup/claim", headers=SUP).status_code == 200
    assert client.post(f"{base}/followup/claim", headers=NADIA).status_code == 409
    same = client.post(f"{base}/followup", headers=SUP,
                       json={"outcome": "reached_independently", "channel": "registered_number"})
    assert same.status_code == 422
    assert same.json()["error"]["code"] == "SAME_HANDSET_NOT_INDEPENDENT"
    # An agent-provided or alternate number is not even a field.
    extra = client.post(f"{base}/followup", headers=SUP, json={
        "outcome": "attempted", "channel": "registered_number", "phone": "01712345678"})
    assert extra.status_code == 422
    # Another supervisor cannot record on this follow-up.
    assert client.post(f"{base}/followup", headers=NADIA, json={
        "outcome": "uncertain", "channel": "in_person"}).status_code == 403
    for outcome in ("attempted", "uncertain", "unreachable"):
        done = client.post(f"{base}/followup", headers=SUP, json={
            "outcome": outcome, "channel": "registered_number", "note": "no answer from handset"})
        assert done.status_code == 200 and done.json()["followup_status"] == outcome
        assert _decide(task["case_id"], "approved").status_code == 409   # still unresolved
    detail = _task(durable_service, out["txn_id"])
    assert detail["followup_attempts"] == 3
    assert any(h["action"] == "followup_recorded" for h in detail["history"])


def test_in_person_independent_contact_allows_clearing_once(durable_service, setup):
    out, task = _mismatch_case(durable_service, setup)
    base = f"/api/v1/callcenter/tasks/{task['task_id']}"
    assigned = client.post(f"{base}/followup/assign", headers=ADMIN,
                           json={"staff_id": "supervisor_777"})
    assert assigned.status_code == 200
    assert assigned.json()["followup_assigned_to"] == "supervisor_777"
    assert client.post(f"{base}/followup/claim", headers=NADIA).status_code == 409
    ok = client.post(f"{base}/followup", headers=SUP, json={
        "outcome": "reached_independently", "channel": "in_person", "note": "branch visit"})
    assert ok.status_code == 200 and ok.json()["followup_status"] == "reached_independently"
    assert _decide(task["case_id"], "approved").status_code == 200
    again = client.post(f"{base}/followup", headers=SUP, json={
        "outcome": "attempted", "channel": "in_person"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "FOLLOWUP_DONE"
    notes = _scalar(durable_service, "SELECT count(*) FROM case_notes WHERE case_id = %s AND "
                                     "body LIKE 'Independent follow-up:%%';", (task["case_id"],))
    assert notes == 1


def test_audit_report_path_also_cannot_clear_a_case_without_independent_contact(
        durable_service, setup):
    out, task = _mismatch_case(durable_service, setup)
    case_id, base = task["case_id"], f"/api/v1/callcenter/tasks/{task['task_id']}"
    assert client.post(f"/api/v1/cases/{case_id}/claim", headers=SUP).status_code == 200
    report = {"decision": "approved", "risk_level": "low", "customer_contacted": True,
              "findings": "Customer says it was a typing error.",
              "action_taken": "None"}
    refused = client.post(f"/api/v1/cases/{case_id}/audit-report", headers=SUP, json=report)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "INDEPENDENT_CONTACT_REQUIRED"
    still_open = _scalar(durable_service, "SELECT status FROM cases WHERE case_id = %s;",
                         (case_id,))
    assert still_open == "open"
    # An escalation report is still possible, and clearing works after independent contact.
    escalate = client.post(f"/api/v1/cases/{case_id}/audit-report", headers=SUP,
                           json={**report, "decision": "escalated", "risk_level": "high"})
    assert escalate.status_code == 201
    client.post(f"{base}/followup/claim", headers=SUP)
    client.post(f"{base}/followup", headers=SUP, json={
        "outcome": "reached_independently", "channel": "in_person"})
    cleared = client.post(f"/api/v1/cases/{case_id}/audit-report", headers=SUP, json=report)
    assert cleared.status_code == 201 and cleared.json()["decision"] == "approved"


def test_verified_check_has_no_followup_and_roles_are_enforced(durable_service, setup):
    voice = setup(FlakyProvider())
    out = _cashout(2000)
    call_id = _task(durable_service, out["txn_id"])["calls"][0]["call_id"]
    voice.handle_digits(call_id, "2000", "")
    task = _task(durable_service, out["txn_id"])
    assert task["check_status"] == "verified" and task["followup_status"] == "not_required"
    base = f"/api/v1/callcenter/tasks/{task['task_id']}"
    body = {"outcome": "attempted", "channel": "in_person"}
    assert client.post(f"{base}/followup", headers=ADMIN, json=body
                       ).json()["error"]["code"] == "NO_FOLLOWUP_REQUIRED"
    for headers in (AGENT, CUSTOMER):
        assert client.post(f"{base}/followup", headers=headers, json=body).status_code == 403
        assert client.post(f"{base}/followup/claim", headers=headers).status_code == 403
    # only supervisors claim a follow-up
    assert client.post(f"{base}/followup/claim", headers=ADMIN).status_code == 403


def test_followup_state_never_reaches_agent_or_customer_payloads(durable_service, setup):
    out, task = _mismatch_case(durable_service, setup)
    for headers in (AGENT, CUSTOMER):
        text = client.get("/api/v1/transactions", headers=headers).text.lower()
        for word in ("followup", "follow_up", "suspicious", "mismatch", "duress", "case_id",
                     "independent", "required"):
            assert word not in text, (word, text[:200])


def test_retry_wording_does_not_announce_a_mismatch():
    from app.voice import scripts

    for language in ("bn", "banglish", "en"):
        for key in ("retry", "mandate_retry"):
            text = scripts.line(language, key).lower()
            assert "match" not in text and "মেল" not in text and "sorry" not in text


# ------------------------------------------------------------------ audit trail and transcripts
def test_audit_log_is_append_only_at_the_database(durable_service):
    import psycopg

    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES ('t', 'test_event', 'x', '1', 'v1.0', '{}'::jsonb, now()) "
                    "RETURNING log_id;")
        log_id = cur.fetchone()[0]
        conn.commit()
    for sql in ("UPDATE audit_log SET actor = 'evil' WHERE log_id = %s;",
                "DELETE FROM audit_log WHERE log_id = %s;"):
        with durable_service.get_connection() as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                cur.execute(sql, (log_id,))
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            cur.execute("TRUNCATE audit_log;")
    assert _scalar(durable_service, "SELECT actor FROM audit_log WHERE log_id = %s;",
                   (log_id,)) == "t"


def test_transcripts_are_redacted_and_purged_after_retention(durable_service, setup):
    voice = setup(FlakyProvider())
    out = _cashout(3000)
    center = CallCenterService(durable_service, policy=lambda: POLICY)
    call_id = _task(durable_service, out["txn_id"])["calls"][0]["call_id"]
    voice.handle_digits(call_id, "", "", speech="call me on 01712345678 about U_123456",
                        confidence=0.9)
    row = _scalar(durable_service, "SELECT raw_input FROM call_responses WHERE check_id = "
                                   "(SELECT check_id FROM txn_checks WHERE txn_id = %s) "
                                   "ORDER BY response_id DESC LIMIT 1;", (out["txn_id"],))
    assert "01712345678" not in row and "U_123456" not in row and "[hidden]" in row
    assert center.purge_transcripts(30) == 0                       # still inside retention
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE call_responses SET created_at = now() - interval '40 days';")
        conn.commit()
    assert center.purge_transcripts(30) >= 1
    assert _scalar(durable_service, "SELECT count(*) FROM call_responses "
                                    "WHERE raw_input IS NOT NULL;") == 0
    # The parsed outcome and an audit event remain.
    assert _scalar(durable_service, "SELECT count(*) FROM call_responses "
                                    "WHERE interpreted = 'unclear';") >= 1
    assert _scalar(durable_service, "SELECT count(*) FROM audit_log "
                                    "WHERE action = 'transcripts_purged';") == 1
