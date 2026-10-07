"""Post-transaction confirmation: record cash-out, call customer, verified or suspicious."""

from __future__ import annotations

import json

import pytest
from app.copilot import router as copilot_router
from app.copilot.investigator import CaseInvestigator
from app.main import app
from app.mandates.service import MandateService
from app.notify import router as notify_router
from app.notify.service import NotificationService, SimulatedSmsProvider
from app.txn.service import TxnCheckService, recommendation
from app.voice import router as voice_router
from app.voice.providers import SimulatedVoiceProvider
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}
ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}


@pytest.fixture(autouse=True)
def services(durable_service: MandateService):
    voice = VoiceService(durable_service, SimulatedVoiceProvider())
    voice_router.set_voice_service(voice)
    notify_router.set_notification_service(
        NotificationService(durable_service.get_connection, SimulatedSmsProvider(), {}))
    copilot_router.set_investigator(CaseInvestigator([]))
    yield voice
    voice_router.set_voice_service(None)
    notify_router.set_notification_service(None)
    copilot_router.set_investigator(None)


def _cashout(amount=3000) -> dict:
    res = client.post("/api/v1/cashouts", headers=AGENT,
                      json={"user_id": "U_001", "amount": amount})
    assert res.status_code == 201, res.text
    return res.json()


def _answer(digits: str) -> dict:
    calls = client.get("/api/v1/voice/incoming", headers=CUSTOMER).json()["calls"]
    assert calls and calls[0]["kind"] == "transaction"
    res = client.post(f"/api/v1/voice/calls/{calls[0]['call_id']}/simulated-answer",
                      headers=CUSTOMER, json={"digits": digits})
    assert res.status_code == 200, res.text
    return res.json()


def _check(txn_id: int) -> dict:
    items = client.get("/api/v1/transaction-checks", headers=ANALYST).json()["items"]
    return next(i for i in items if i["txn_id"] == txn_id)


def test_cashout_debits_ledger_and_calls_customer(durable_service):
    before = TxnCheckService(durable_service).balance("U_001")
    out = _cashout(3000)
    assert out["check"] == "waiting" and out["amount"] == 3000.0 and out["fee"] == 45.0
    assert "balance_after" not in out  # the agent never sees the customer's balance
    assert TxnCheckService(durable_service).balance("U_001") == before - 3045.0
    calls = client.get("/api/v1/voice/incoming", headers=CUSTOMER).json()["calls"]
    assert "3000" not in json.dumps(calls)  # the call never says the amount
    assert _check(out["txn_id"])["status"] == "calling"
    sms = client.get("/api/v1/notifications", headers=CUSTOMER).json()["items"]
    assert sms[0]["template"] == "cashout_notice"
    # The SMS must not show the ledger amount before the customer states the cash received.
    body = sms[0]["body"]
    assert "3000" not in body and "৩,০০০" not in body and "৩০০০" not in body


def test_matching_amount_is_verified(durable_service):
    out = _cashout(2000)
    answer = _answer("2000")
    assert answer["call_ended"] is True
    check = _check(out["txn_id"])
    assert check["status"] == "verified" and check["outcome"] == "match"
    assert check["case_id"] is None and check["recommendation"]["label"] == "verified"
    # Agent and customer only see neutral states.
    agent_view = client.get("/api/v1/transactions", headers=AGENT).json()["items"][0]
    assert agent_view["check"] == "done" and "status" not in agent_view
    customer = client.get("/api/v1/transactions", headers=CUSTOMER).json()
    assert customer["items"][0]["check"] == "done" and customer["balance"] is not None


def test_mismatch_retries_once_then_flags_suspicious(durable_service):
    out = _cashout(3000)
    first = _answer("2900")
    assert first["call_ended"] is False
    assert _check(out["txn_id"])["status"] == "calling"
    _answer("2900")
    check = _check(out["txn_id"])
    assert check["status"] == "suspicious" and check["outcome"] == "mismatch"
    assert check["stated_amount"] == 2900.0
    rec = check["recommendation"]
    assert rec["label"] == "suspicious" and "fraud" not in json.dumps(rec).lower().replace(
        "not a fraud decision", "")
    case = next(c for c in durable_service.cases if c["case_id"] == check["case_id"])
    assert case["reason"] == "post_txn_amount_mismatch"
    assert case["evidence"]["difference"] == 100.0


def test_denied_and_secret_help_are_suspicious_and_hidden(durable_service):
    denied = _cashout(1000)
    _answer("*")
    assert _check(denied["txn_id"])["outcome"] == "denied"
    duress = _cashout(1500)
    spoken = _answer("01500")
    assert "duress" not in json.dumps(spoken)
    check = _check(duress["txn_id"])
    assert check["outcome"] == "duress" and check["status"] == "suspicious"
    reasons = {c["reason"] for c in durable_service.cases}
    assert {"customer_denied_transaction", "duress_signal"} <= reasons
    cases = client.get("/api/v1/ops/cases", headers=ANALYST).json()["cases"]
    assert cases[0]["reason"] == "duress_signal" and cases[0]["priority"] == "urgent"
    states = {i["check"] for i in client.get("/api/v1/transactions", headers=AGENT).json()[
        "items"]}
    assert states == {"done"}


def test_no_answer_then_supervisor_calls_again(durable_service, services):
    out = _cashout(500)
    check = _check(out["txn_id"])
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT call_id FROM voice_calls WHERE check_id = %s;", (check["check_id"],))
        call_id = str(cur.fetchone()[0])
    services.provider_status(call_id, "no-answer")
    assert _check(out["txn_id"])["status"] == "no_answer"
    assert client.get("/api/v1/transactions", headers=AGENT).json()["items"][0]["check"] == "missed"
    again = client.post(f"/api/v1/transaction-checks/{check['check_id']}/call", headers=ANALYST)
    assert again.status_code == 200 and again.json()["status"] == "calling"
    _answer("500")
    assert _check(out["txn_id"])["status"] == "verified"
    closed = client.post(f"/api/v1/transaction-checks/{check['check_id']}/call", headers=ANALYST)
    assert closed.status_code == 409


def test_cashout_rules_and_roles(durable_service):
    other = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_002'])}"}
    assert client.post("/api/v1/cashouts", headers=other,
                       json={"user_id": "U_001", "amount": 100}).status_code == 403
    assert client.post("/api/v1/cashouts", headers=ANALYST,
                       json={"user_id": "U_001", "amount": 100}).status_code == 403
    too_big = client.post("/api/v1/cashouts", headers=AGENT, json={"user_id": "U_001",
                                                                  "amount": 999999})
    assert too_big.status_code == 422 and too_big.json()["error"]["code"] == "AMOUNT_EXCEEDS_CAP"
    assert client.post("/api/v1/cashouts", headers=AGENT,
                       json={"user_id": "U_001", "amount": "abc"}).status_code == 422
    assert client.get("/api/v1/transaction-checks", headers=AGENT).status_code == 403
    assert client.get("/api/v1/transactions", headers=ANALYST).status_code == 403
    assert client.get("/api/v1/transaction-checks?status=bogus",
                      headers=ANALYST).status_code == 422


def test_supervisor_views_dashboard_timeline_and_ai_summary(durable_service):
    out = _cashout(3000)
    _answer("2500")
    _answer("2500")
    check = _check(out["txn_id"])
    detail = client.get(f"/api/v1/transaction-checks/{check['check_id']}", headers=ANALYST).json()
    assert detail["calls"] and detail["recommendation"]["headline"]
    filtered = client.get("/api/v1/transaction-checks?status=suspicious", headers=ANALYST).json()
    assert [i["txn_id"] for i in filtered["items"]] == [out["txn_id"]]
    overview = client.get("/api/v1/ops/overview", headers=ANALYST).json()
    assert overview["check_totals"]["suspicious"] == 1 and overview["check_totals"]["cashouts"] == 1
    timeline = client.get(f"/api/v1/cases/{check['case_id']}/timeline", headers=ANALYST).json()
    labels = [e["label"] for e in timeline["events"]]
    assert "cashout_recorded" in labels
    assert any(label.startswith("Marked suspicious by a fixed rule") for label in labels)
    brief = client.post(f"/api/v1/cases/{check['case_id']}/brief", headers=ANALYST).json()
    assert brief["brief"]["headline"].startswith("Customer typed a different amount")
    assert any(f["field"] == "transaction.customer_typed_bdt" for f in brief["facts"])


def test_recommendation_wording():
    from decimal import Decimal

    ok = recommendation("match", Decimal(1000), Decimal(1000), {})
    assert ok["label"] == "verified" and ok["next_step"] is None
    bad = recommendation("mismatch", Decimal(1000), Decimal(900),
                         {"flagged_30d": 2, "watchlisted": True, "agent_score": 0.9})
    texts = " ".join(r["text"] for r in bad["reasons"])
    assert "less by ৳100" in texts and "2 other suspicious" in texts
    assert "not a fraud decision" in bad["note"]
