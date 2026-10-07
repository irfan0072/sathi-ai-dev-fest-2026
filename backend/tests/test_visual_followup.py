"""Regression tests for the browser-review findings (state mapping, fixtures, evidence, gating)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from app.analytics.router import set_analytics_service
from app.analytics.service import AnalyticsService
from app.callcenter.service import CallCenterService
from app.main import app
from app.mandates.router import set_mandate_service
from app.scam.seed import MINIMAL_USERS, seed_minimal_scam_demo
from app.txn.router import _public
from app.txn.service import TxnCheckService
from fastapi.testclient import TestClient
from tests.artifact_fixture import write_test_bundle
from tests.conftest import create_test_token

client = TestClient(app)
ADMIN = {"Authorization": f"Bearer {create_test_token('admin_777', 'super_admin')}"}
SUP = {"Authorization": f"Bearer {create_test_token('supervisor_777', 'supervisor')}"}
ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_777', 'analyst')}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}


@pytest.fixture(autouse=True)
def database(durable_service, tmp_path):
    set_mandate_service(durable_service)
    set_analytics_service(AnalyticsService(mandate_service=durable_service,
                                           artifact_dir=write_test_bundle(tmp_path / "b")))
    yield
    set_analytics_service(None)


# ------------------------------------------------------------ unreachable is not "answered"
@pytest.mark.parametrize(("status", "expected"), [
    ("pending", "waiting"), ("calling", "waiting"), ("no_answer", "missed"),
    ("unreachable", "unreachable"), ("manual_review", "manual"),
    ("verified", "done"), ("suspicious", "done"),            # suspicious stays hidden
])
def test_public_state_mapping_is_honest_and_hides_results(status, expected):
    item = {"txn_id": 1, "amount": 500.0, "fee": 7.5, "ts": "t", "status": status,
            "user_id": "U", "agent_id": "A", "balance_after": 1.0}
    assert _public(item, "customer")["check"] == expected
    assert _public(item, "agent")["check"] == expected


def test_exhausted_calls_reach_customer_and_agent_screens_as_not_reached(durable_service):
    check = TxnCheckService(durable_service).record_cashout("A_001", "U_001", 500)
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE txn_checks SET status = 'unreachable' WHERE check_id = %s;",
                    (check["check_id"],))
        conn.commit()
    for headers in (CUSTOMER, AGENT):
        item = client.get("/api/v1/transactions", headers=headers).json()["items"][0]
        assert item["check"] == "unreachable"
        assert item["fee"] == 7.5                              # exact cents reach the API
        assert "outcome" not in item and "case_id" not in item


# ------------------------------------------------------------ money and ledger
def test_exact_fee_cents_in_all_transactions(durable_service):
    TxnCheckService(durable_service).record_cashout("A_001", "U_001", 500)
    items = client.get("/api/v1/admin/transactions", headers=ADMIN).json()["items"]
    cash_out = next(i for i in items if i["txn_type"] == "cash_out")
    assert cash_out["fee"] == 7.5 and cash_out["amount"] == 500.0


# ------------------------------------------------------------ case file / timeline follow-up
def test_case_views_show_followup_and_the_neutral_rule_label(durable_service):
    svc = TxnCheckService(durable_service)
    check = svc.record_cashout("A_001", "U_001", 700)
    svc.handle_answer(check["check_id"], "0700")
    case_id = svc.get(check["check_id"])["case_id"]
    timeline = client.get(f"/api/v1/cases/{case_id}/timeline", headers=ANALYST).json()
    assert timeline["followup"] == {"status": "required", "attempts": 0, "blocks_clearing": True}
    labels = " ".join(e["label"] for e in timeline["events"])
    assert "AI marked" not in labels and "fixed rule" in labels
    file = client.get(f"/api/v1/cases/{case_id}/file", headers=ADMIN).json()
    assert file["followup"]["blocks_clearing"] is True


# ------------------------------------------------------------ small scam fixtures
def test_minimal_scam_fixtures_work_without_the_scale_population(durable_service):
    first = seed_minimal_scam_demo(durable_service.get_connection)
    assert first["seeded"] and first["reports"] == 3
    assert seed_minimal_scam_demo(durable_service.get_connection)["seeded"] is False
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO transactions (user_id, txn_type, credit_source, amount, "
                    "balance_after, channel, ts) VALUES ('U_001', 'credit', 'salary', 1, 1, "
                    "'app', now());")
        conn.commit()
    check = {n: client.post("/api/v1/payments/check-recipient", headers=CUSTOMER,
                            json={"number": n}).json()
             for n in ("01900000500", "01901000002", "01955555555")}
    assert check["01900000500"]["warning_level"] in ("caution", "high")      # alerted
    assert check["01900000500"]["community_reports"] >= 2
    assert check["01901000002"]["warning_level"] == "none" and check["01901000002"]["exists"]
    assert check["01955555555"]["warning_level"] == "none" and not check["01955555555"]["exists"]
    assert len(MINIMAL_USERS) == 3


# ------------------------------------------------------------ extended benchmark view
def test_benchmark_endpoint_serves_the_verified_archive_read_only():
    body = client.get("/api/v1/metrics/agent-benchmark-v2", headers=ANALYST).json()
    held = body["final_held_out"]
    assert (held["agents"], held["skimmers"], held["honest_agents"],
            held["honest_high_volume"]) == (3600, 120, 3480, 240)
    assert body["agents_generated_total"] == 9000 and body["replications"] == 3
    subtle = next(s for s in body["scenarios"] if s["scenario"] == "subtle")
    assert subtle["methods"]["ensemble_v1"]["recall"]["numerator"] == 0
    assert "NOT deployed" in subtle["methods"]["ensemble_v2_shortfall"]["label"]
    assert client.get("/api/v1/metrics/agent-benchmark-v2", headers=AGENT).status_code == 403
    assert client.get("/api/v1/metrics/agent-benchmark-v2").status_code == 401


def test_benchmark_endpoint_refuses_a_tampered_archive(tmp_path, monkeypatch):
    copy = tmp_path / "agent_v2"
    shutil.copytree(Path("data/benchmarks/agent_v2"), copy)
    final = copy / "final_results.json"
    final.write_text(final.read_text().replace('"skimmers": 120', '"skimmers": 121', 1))
    monkeypatch.setenv("SATHI_BENCHMARK_V2_DIR", str(copy))
    res = client.get("/api/v1/metrics/agent-benchmark-v2", headers=ANALYST)
    assert res.status_code == 503 and res.json()["error"]["code"] == "BENCHMARK_UNAVAILABLE"
    monkeypatch.setenv("SATHI_BENCHMARK_V2_DIR", str(tmp_path / "missing"))
    assert client.get("/api/v1/metrics/agent-benchmark-v2", headers=ANALYST).status_code == 503


# ------------------------------------------------------------ priority across lifecycles
def test_urgent_priority_survives_resolution_hooks(durable_service):
    svc = TxnCheckService(durable_service)
    check = svc.record_cashout("A_001", "U_001", 700)
    svc.handle_answer(check["check_id"], "0700")
    center = CallCenterService(durable_service)
    center.on_resolved(check["check_id"], "suspicious")
    center.on_resolved(check["check_id"], "verified")
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT priority FROM call_tasks WHERE check_id = %s;", (check["check_id"],))
        assert cur.fetchone()[0] == "urgent"
