"""Repeatable SYNTHETIC end-to-end scenario through the real backend.

cash-out -> confirmation call -> honest match / mismatch / secret help / silence / uncertain
speech / provider failure -> supervisor queue -> evidence -> independent follow-up -> human
decision -> audit trail, plus wrong-role denials.

Everything runs through the real HTTP routes, services and PostgreSQL schema (no hard-coded
success states). The only simulated parts are the ones the project has always simulated: the
voice provider (the customer handset answers through the simulated-answer route), the SMS
provider, and the passage of time (a scheduled retry is made due by moving its timestamp).
No call, SMS or paid model request is made. Nothing here is field evidence.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.callcenter import worker as call_worker
from app.copilot.investigator import CaseInvestigator
from app.voice.providers import PlacedCall, SimulatedVoiceProvider, VoiceProviderError

CUSTOMERS = {f"U_DEMO_{i:02d}": i for i in range(1, 9)}
AGENT = "A_DEMO_01"
OTHER_AGENT_CUSTOMER = "U_DEMO_99"


class ScenarioProvider:
    """The simulated provider with a failure switch (a stand-in for a provider outage)."""

    name = "simulated"

    def __init__(self) -> None:
        self.failing = False
        self._ok = SimulatedVoiceProvider()

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall:
        if self.failing:
            raise VoiceProviderError("Provider is down (scenario outage).")
        return self._ok.place_call(to_number, answer_url, status_url)

    def validate_request(self, url: str, params: dict[str, str], signature: str | None) -> bool:
        return False


def seed_scenario_accounts(get_connection) -> None:
    """Synthetic customers and one agent with enough balance for the scenario."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO agents (agent_id, region, volume_band, agent_type) VALUES "
                    "(%s, 'dhaka', 'high', 'high_volume_honest') ON CONFLICT DO NOTHING;",
                    (AGENT,))
        for user in [*CUSTOMERS, OTHER_AGENT_CUSTOMER]:
            cur.execute("INSERT INTO users (user_id, group_label, gender, age_band, region, "
                        "urban_rural) VALUES (%s, 'assisted_allowance', 'female', '41-60', "
                        "'rangpur', 'rural') ON CONFLICT DO NOTHING;", (user,))
            cur.execute("INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, "
                        "amount, fee, balance_after, channel, ts) VALUES (%s, NULL, 'credit', "
                        "'allowance', 50000, 0, 50000, 'app', '2026-09-30T00:00:00Z');", (user,))
        conn.commit()


class Scenario:
    def __init__(self, client, tokens: dict[str, dict[str, str]], mandates, provider,
                 voice_service, set_investigator) -> None:
        self.client, self.tokens, self.mandates = client, tokens, mandates
        self.provider, self.voice, self.set_investigator = provider, voice_service, set_investigator
        self.steps: list[dict[str, Any]] = []
        self.checks: dict[str, int] = {}

    # ------------------------------------------------------------------ plumbing
    def _call(self, scenario: str, label: str, role: str, method: str, path: str,
              expect: int | tuple[int, ...] | None = None, **kwargs) -> tuple[int, Any]:
        headers = self.tokens.get(role, {})
        response = getattr(self.client, method)(path, headers=headers, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {}
        record = {"scenario": scenario, "step": label, "as": role or "anonymous",
                  "http": response.status_code, "at": _now()}
        if isinstance(body, dict) and "error" in body:
            record["error_code"] = body["error"].get("code")
        self.steps.append(record)
        if expect is not None:
            ok = response.status_code in ((expect,) if isinstance(expect, int) else expect)
            if not ok:
                raise AssertionError(f"{scenario}/{label}: expected {expect}, got "
                                     f"{response.status_code}: {response.text[:300]}")
        return response.status_code, body

    def _sql(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.mandates.get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            conn.commit()
            return rows

    def note(self, scenario: str, text: str, **data: Any) -> None:
        self.steps.append({"scenario": scenario, "step": text, "as": "system", "at": _now(),
                           **({"data": data} if data else {})})

    def cash_out(self, scenario: str, user: str, amount: int) -> dict[str, Any]:
        _, body = self._call(scenario, f"agent records a cash-out of {amount}", "agent", "post",
                             "/api/v1/cashouts", 201, json={"user_id": user, "amount": amount})
        self.checks[scenario] = self._sql(
            "SELECT check_id FROM txn_checks WHERE txn_id = %s;", (body["txn_id"],))[0][0]
        return body

    def live_call(self, check_id: int) -> str:
        rows = self._sql("SELECT call_id FROM voice_calls WHERE check_id = %s AND status IN "
                         "('queued','ringing','in_progress') ORDER BY created_at DESC LIMIT 1;",
                         (check_id,))
        return str(rows[0][0]) if rows else ""

    def answer(self, scenario: str, user: str, check_id: int, label: str, **body) -> dict[str, Any]:
        call_id = self.live_call(check_id)
        assert call_id, f"{scenario}: no live call for check {check_id}"
        _, result = self._call(scenario, label, f"customer:{user}", "post",
                               f"/api/v1/voice/calls/{call_id}/simulated-answer", 200, json=body)
        return result

    def check_state(self, check_id: int) -> dict[str, Any]:
        row = self._sql("SELECT c.status, c.outcome, c.case_id, t.status, t.followup_status, "
                        "t.auto_attempts, t.manual_reason, t.placement_failures, t.task_id "
                        "FROM txn_checks c JOIN call_tasks t USING (check_id) "
                        "WHERE c.check_id = %s;", (check_id,))[0]
        return dict(zip(("check", "outcome", "case_id", "task", "followup", "auto_attempts",
                         "manual_reason", "placement_failures", "task_id"), row))

    def make_retry_due(self) -> None:
        self._sql("UPDATE call_tasks SET next_attempt_at = now() - interval '1 second' "
                  "WHERE status = 'retry_scheduled';")

    def tick(self) -> dict[str, int]:
        return call_worker.Worker().tick()

    # ------------------------------------------------------------------ scenarios
    def s1_honest_match(self) -> None:
        s, user = "S1 honest customer, correct amount", "U_DEMO_01"
        self.cash_out(s, user, 3000)
        check = self.checks[s]
        self._call(s, "customer handset shows the incoming call", f"customer:{user}", "get",
                   "/api/v1/voice/incoming", 200)
        self.answer(s, user, check, "customer states the cash they received (3000)", digits="3000")
        state = self.check_state(check)
        assert state["check"] == "verified" and state["followup"] == "not_required", state
        self._call(s, "agent sees only a neutral state", "agent", "get", "/api/v1/transactions",
                   200)

    def s2_mismatch_to_human_decision(self) -> None:
        s, user = "S2 customer states less cash than the ledger", "U_DEMO_02"
        self.cash_out(s, user, 5000)
        check = self.checks[s]
        self.answer(s, user, check, "customer types 3000 (first try)", digits="3000")
        self.answer(s, user, check, "customer types 3000 again (second try)", digits="3000")
        state = self.check_state(check)
        assert state["check"] == "suspicious" and state["followup"] == "required", state
        case_id, task_id = state["case_id"], state["task_id"]
        base = f"/api/v1/callcenter/tasks/{task_id}"
        self._call(s, "supervisor sees the follow-up in the queue", "supervisor", "get",
                   "/api/v1/callcenter/queue?scope=followup", 200)
        self._call(s, "supervisor claims the follow-up", "supervisor", "post",
                   f"{base}/followup/claim", 200)
        self.set_investigator(CaseInvestigator([]))  # deterministic brief, no online model
        _, brief = self._call(s, "supervisor opens the evidence brief", "supervisor", "post",
                              f"/api/v1/cases/{case_id}/brief", 200)
        assert brief["mode"] == "deterministic", brief["mode"]
        self._call(s, "case cannot be cleared yet (no independent contact)",
                   "admin", "post", f"/api/v1/cases/{case_id}/decision", 409,
                   json={"decision": "approved", "note": "should be refused"})
        self._call(s, "supervisor marks the registered handset 'independently reached' "
                      "(refused: same handset proves nothing)", "supervisor", "post", base
                   + "/followup", 422, json={"outcome": "reached_independently",
                                             "channel": "registered_number"})
        self._call(s, "supervisor tries to add an alternate phone number (refused)",
                   "supervisor", "post", f"{base}/followup", 422,
                   json={"outcome": "attempted", "channel": "registered_number",
                         "phone": "01700000000"})
        self._call(s, "supervisor records an attempt on the registered handset",
                   "supervisor", "post", f"{base}/followup", 200,
                   json={"outcome": "attempted", "channel": "registered_number",
                         "note": "Customer says the amount received was 3000."})
        self._call(s, "case still cannot be cleared", "admin", "post",
                   f"/api/v1/cases/{case_id}/decision", 409,
                   json={"decision": "approved", "note": "still refused"})
        self._call(s, "in-person independent contact confirms the shortfall [PENDING in a real "
                      "deployment: simulated here]", "supervisor", "post", f"{base}/followup",
                   200, json={"outcome": "reached_independently", "channel": "in_person",
                              "note": "Synthetic: in-person contact recorded by the demo."})
        self._call(s, "supervisor takes the case", "supervisor", "post",
                   f"/api/v1/cases/{case_id}/claim", 200)
        self._call(s, "human decision: confirmed problem", "supervisor", "post",
                   f"/api/v1/cases/{case_id}/decision", 200,
                   json={"decision": "denied", "note": "Confirmed by independent contact."})
        audit = self._sql("SELECT action FROM audit_log WHERE entity_id = %s OR (entity = 'case' "
                          "AND entity_id = %s) ORDER BY log_id;", (str(task_id), str(case_id)))
        self.note(s, "audit trail for this task and case", actions=[a[0] for a in audit])

    def s3_secret_help(self) -> None:
        s, user = "S3 customer uses the secret help signal", "U_DEMO_03"
        self.cash_out(s, user, 2000)
        check = self.checks[s]
        result = self.answer(s, user, check, "customer types 02000 (leading zero = help)",
                             digits="02000")
        state = self.check_state(check)
        assert state["check"] == "suspicious" and state["outcome"] == "duress", state
        self.note(s, "the handset only hears the neutral closing sentence",
                  spoken=result["spoken"])
        case_id, task_id = state["case_id"], state["task_id"]
        self._call(s, "urgent case is visible to staff", "admin", "get",
                   "/api/v1/ops/cases", 200)
        txns = self._call(s, "agent view stays neutral", "agent", "get", "/api/v1/transactions",
                          200)[1]
        flat = str(txns).lower()
        assert "duress" not in flat and "suspicious" not in flat and "followup" not in flat
        base = f"/api/v1/callcenter/tasks/{task_id}"
        self._call(s, "supervisor claims the independent follow-up", "supervisor", "post",
                   f"{base}/followup/claim", 200)
        self._call(s, "contact attempt: no independent contact possible, outcome uncertain",
                   "supervisor", "post", f"{base}/followup", 200,
                   json={"outcome": "uncertain", "channel": "registered_number",
                         "note": "Could not confirm the customer was alone."})
        self._call(s, "uncertain contact: case cannot be cleared", "admin", "post",
                   f"/api/v1/cases/{case_id}/decision", 409,
                   json={"decision": "approved", "note": "refused while uncertain"})
        self._call(s, "case stays open and is escalated to the fraud team", "admin", "post",
                   f"/api/v1/cases/{case_id}/decision", 200,
                   json={"decision": "escalated", "note": "Uncertain contact: escalate."})

    def s4_silence_then_retry(self) -> None:
        s, user = "S4 customer is silent, then answers on the retry", "U_DEMO_04"
        self.cash_out(s, user, 1500)
        check = self.checks[s]
        self.answer(s, user, check, "customer picks up, says nothing (1st silence)", no_input=True)
        self.answer(s, user, check, "customer says nothing again (2nd silence)", no_input=True)
        state = self.check_state(check)
        assert state["task"] == "retry_scheduled" and state["check"] == "no_answer", state
        self.note(s, "silence is never a denial: a retry is scheduled", **state)
        self.make_retry_due()
        self.tick()
        self.answer(s, user, check, "retry call: customer types 1500", digits="1500")
        state = self.check_state(check)
        assert state["check"] == "verified" and state["auto_attempts"] == 2, state

    def s5_uncertain_speech(self) -> None:
        s, user = "S5 uncertain speech goes to a person", "U_DEMO_05"
        self.cash_out(s, user, 2500)
        check = self.checks[s]
        self.answer(s, user, check, "customer says 'approximately two thousand five hundred'",
                    digits="", speech="approximately two thousand five hundred", confidence=0.95)
        assert self.check_state(check)["check"] == "calling"
        self.answer(s, user, check, "customer mumbles (low confidence)", digits="",
                    speech="umm ami bujhi nai", confidence=0.3)
        state = self.check_state(check)
        assert state["task"] == "needs_manual" and state["check"] == "manual_review", state
        task_id = state["task_id"]
        self._call(s, "supervisor sees the call in the pending queue", "supervisor", "get",
                   "/api/v1/callcenter/queue?scope=pending", 200)
        self._call(s, "supervisor claims it", "supervisor", "post",
                   f"/api/v1/callcenter/tasks/{task_id}/claim", 200)
        self._call(s, "supervisor logs the call: customer confirmed 2500", "supervisor", "post",
                   f"/api/v1/callcenter/tasks/{task_id}/outcome", 200,
                   json={"result": "confirmed", "stated_amount": 2500,
                         "note": "Customer confirmed on a supervised call."})
        assert self.check_state(check)["check"] == "verified"

    def s6_provider_failure(self) -> None:
        s, user = "S6 call provider is down at the first attempt", "U_DEMO_06"
        self.provider.failing = True
        self.cash_out(s, user, 1000)
        check = self.checks[s]
        state = self.check_state(check)
        assert state["task"] == "retry_scheduled" and state["placement_failures"] == 1, state
        self.note(s, "the committed cash-out is not stranded: a bounded retry is scheduled",
                  **state)
        self.provider.failing = False
        self.make_retry_due()
        self.tick()
        self.answer(s, user, check, "provider recovered; customer types 1000", digits="1000")
        assert self.check_state(check)["check"] == "verified"

        s2, user2 = "S6b provider stays down until attempts run out", "U_DEMO_07"
        self.provider.failing = True
        self.cash_out(s2, user2, 800)
        check2 = self.checks[s2]
        for _ in range(3):
            self.make_retry_due()
            self.tick()
        state = self.check_state(check2)
        assert state["task"] == "needs_manual" and state["manual_reason"] == "provider_failure", \
            state
        self.provider.failing = False
        self.note(s2, "after the last attempt a person takes over (no money was reversed)", **state)
        balance = self._sql("SELECT balance_after FROM transactions WHERE user_id = %s "
                            "ORDER BY txn_id DESC LIMIT 1;", (user2,))[0][0]
        assert float(balance) < 50000

    def s7_wrong_role_paths(self) -> None:
        s = "S7 wrong-role and ownership paths"
        self._call(s, "agent cannot read the supervisor queue", "agent", "get",
                   "/api/v1/callcenter/queue", 403)
        self._call(s, "customer cannot list transaction checks", "customer:U_DEMO_01", "get",
                   "/api/v1/transaction-checks", 403)
        self._call(s, "agent cannot cash out for another agent's customer", "agent", "post",
                   "/api/v1/cashouts", 403, json={"user_id": OTHER_AGENT_CUSTOMER, "amount": 500})
        self._call(s, "anonymous caller is refused", "", "get", "/api/v1/transactions", 401)
        self._call(s, "agent cannot record an independent follow-up", "agent", "post",
                   "/api/v1/callcenter/tasks/1/followup", 403,
                   json={"outcome": "attempted", "channel": "in_person"})
        self._call(s, "customer cannot answer someone else's call", "customer:U_DEMO_02", "post",
                   f"/api/v1/voice/calls/{self._any_call()}/simulated-answer", 403,
                   json={"digits": "1"})

    def _any_call(self) -> str:
        return str(self._sql("SELECT call_id FROM voice_calls WHERE user_id = 'U_DEMO_01' "
                             "LIMIT 1;")[0][0])

    def run(self) -> dict[str, Any]:
        for step in (self.s1_honest_match, self.s2_mismatch_to_human_decision,
                     self.s3_secret_help, self.s4_silence_then_retry, self.s5_uncertain_speech,
                     self.s6_provider_failure, self.s7_wrong_role_paths):
            step()
        _, evidence = self._call("Evidence", "workflow evidence from this database", "admin",
                                 "get", "/api/v1/ops/workflow-evidence", 200)
        _, economics = self._call("Evidence", "assumption-based economics", "admin", "get",
                                  "/api/v1/ops/economics", 200)
        return {"steps": self.steps, "workflow_evidence": evidence,
                "economics_baseline": economics["baseline"],
                "label": "SYNTHETIC local scenario through the real backend; not field evidence"}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _login(client, principal: str, pin: str) -> dict[str, str] | None:
    response = client.post("/api/v1/auth/demo-login", json={"principal": principal, "pin": pin})
    if response.status_code != 200:
        return None
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def run_scenario(mandates) -> dict[str, Any]:
    """Wire the real services to one database (schema) and run every scenario."""
    from fastapi.testclient import TestClient

    from app.analytics.router import set_analytics_service
    from app.analytics.service import AnalyticsService
    from app.auth.jwt import create_access_token
    from app.copilot import router as copilot_router
    from app.main import app
    from app.mandates.router import set_mandate_service
    from app.notify import router as notify_router
    from app.notify.service import NotificationService, SimulatedSmsProvider
    from app.voice import router as voice_router
    from app.voice.service import VoiceService

    set_mandate_service(mandates)
    seed_scenario_accounts(mandates.get_connection)
    provider = ScenarioProvider()
    voice = VoiceService(mandates, provider)
    voice_router.set_voice_service(voice)
    notify_router.set_notification_service(
        NotificationService(mandates.get_connection, SimulatedSmsProvider(), {}))
    set_analytics_service(AnalyticsService(mandate_service=mandates))
    client = TestClient(app)

    def token(subject: str, role: str, users: list[str] | None = None) -> dict[str, str]:
        claims = {"sub": subject, "role": role, "principal": subject,
                  "allowed_users": users or [], "scope": "synthetic_demo"}
        return {"Authorization": f"Bearer {create_access_token(claims, expires_in_seconds=1800)}"}

    # The published synthetic staff sign-in is exercised for real; direct tokens only fill gaps.
    tokens = {
        "agent": token(AGENT, "agent", list(CUSTOMERS)),
        "supervisor": _login(client, "demo_supervisor", "3456")
        or token("supervisor_777", "supervisor"),
        "admin": _login(client, "demo_admin", "7890") or token("admin_777", "super_admin"),
        "": {},
    }
    for user in [*CUSTOMERS, OTHER_AGENT_CUSTOMER]:
        tokens[f"customer:{user}"] = token(user, "customer_channel")
    try:
        return Scenario(client, tokens, mandates, provider, voice,
                        copilot_router.set_investigator).run()
    finally:
        copilot_router.set_investigator(None)
        voice_router.set_voice_service(None)
        notify_router.set_notification_service(None)
        set_analytics_service(None)
