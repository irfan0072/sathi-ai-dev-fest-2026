"""Role split: supervisor (works calls and cases) vs super admin (full platform access).

Supervisor: shared pending queues, claim one by one, notes, audit reports, decisions on
their own cases. No settings, no platform analytics, no directories, no staff management.
Super admin: everything, including assigning work to a named supervisor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.analytics.router import set_analytics_service
from app.analytics.service import AnalyticsService
from app.main import app
from app.mandates.service import MandateService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_services(durable_service: MandateService, tmp_path: Path) -> None:
    set_analytics_service(AnalyticsService(mandate_service=durable_service,
                                           artifact_dir=tmp_path / "bundle"))


def _headers(subject: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_test_token(subject, role)}"}


def _open_case(durable_service: MandateService) -> int:
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cases (agent_id, reason, evidence, status) VALUES "
                    "('A_001', 'post_txn_amount_mismatch', '{}'::jsonb, 'open') "
                    "RETURNING case_id;")
        case_id = cur.fetchone()[0]
        conn.commit()
    return case_id


SUPERVISOR_DENIED = (
    ("GET", "/api/v1/settings"), ("GET", "/api/v1/ops/overview"), ("GET", "/api/v1/outreach"),
    ("GET", "/api/v1/liquidity/overview"), ("GET", "/api/v1/admin/overview"),
    ("GET", "/api/v1/admin/users"), ("GET", "/api/v1/admin/agents"),
    ("GET", "/api/v1/admin/staff"), ("GET", "/api/v1/admin/transactions"),
    ("GET", "/api/v1/callcenter/stats"), ("POST", "/api/v1/callcenter/distribute"),
    ("POST", "/api/v1/cases/distribute"), ("GET", "/api/v1/transaction-checks"),
)
SUPERVISOR_ALLOWED = (
    "/api/v1/cases", "/api/v1/ops/cases", "/api/v1/workdesk/summary",
    "/api/v1/workdesk/cases?scope=pending", "/api/v1/workdesk/cases?scope=mine",
    "/api/v1/callcenter/queue?scope=pending", "/api/v1/callcenter/queue?scope=mine",
    "/api/v1/workdesk/reports",
)


@pytest.mark.parametrize(("method", "path"), SUPERVISOR_DENIED)
def test_supervisor_cannot_reach_admin_surfaces(supervisor_headers, method, path):
    res = client.request(method, path, headers=supervisor_headers)
    assert res.status_code == 403, (path, res.text)


@pytest.mark.parametrize("path", SUPERVISOR_ALLOWED)
def test_supervisor_reaches_work_queues(supervisor_headers, path):
    res = client.get(path, headers=supervisor_headers)
    assert res.status_code == 200, (path, res.text)


def test_supervisor_cannot_see_admin_only_call_queues(supervisor_headers):
    res = client.get("/api/v1/callcenter/queue?scope=ignored", headers=supervisor_headers)
    assert res.status_code == 403


def test_supervisor_cannot_modify_watchlist(supervisor_headers):
    res = client.put("/api/v1/watchlist/A_001", headers=supervisor_headers,
                     json={"reason": "not allowed", "case_id": None})
    assert res.status_code == 403


@pytest.mark.parametrize("path", (
    "/api/v1/admin/overview", "/api/v1/admin/users", "/api/v1/admin/agents",
    "/api/v1/admin/staff", "/api/v1/admin/transactions", "/api/v1/admin/audit-log",
    "/api/v1/callcenter/stats", "/api/v1/callcenter/queue?scope=all",
    "/api/v1/workdesk/cases?scope=all", "/api/v1/settings", "/api/v1/ops/overview",
))
def test_super_admin_reaches_everything(super_admin_headers, path):
    res = client.get(path, headers=super_admin_headers)
    assert res.status_code == 200, (path, res.text)


def test_agent_and_customer_blocked_from_staff_tools():
    for role, sub in (("agent", "A_001"), ("customer_channel", "U_001")):
        h = _headers(sub, role)
        for path in ("/api/v1/admin/overview", "/api/v1/callcenter/queue",
                     "/api/v1/workdesk/summary"):
            assert client.get(path, headers=h).status_code == 403, (role, path)


def test_supervisor_decides_only_own_cases(durable_service, supervisor_headers):
    case_id = _open_case(durable_service)
    body = {"decision": "approved", "reviewer": "x", "note": "checked"}
    assert client.post(f"/api/v1/cases/{case_id}/decision", headers=supervisor_headers,
                       json=body).status_code == 403
    assert client.post(f"/api/v1/cases/{case_id}/claim",
                       headers=supervisor_headers).status_code == 200
    res = client.post(f"/api/v1/cases/{case_id}/decision", headers=supervisor_headers, json=body)
    assert res.status_code == 200, res.text


def test_two_supervisors_cannot_claim_same_case(durable_service, supervisor_headers):
    case_id = _open_case(durable_service)
    other = _headers("sup_nadia", "supervisor")
    assert client.post(f"/api/v1/cases/{case_id}/claim",
                       headers=supervisor_headers).status_code == 200
    res = client.post(f"/api/v1/cases/{case_id}/claim", headers=other)
    assert res.status_code == 409
    assert client.post(f"/api/v1/cases/{case_id}/notes", headers=other,
                       json={"note_type": "message", "body": "hi"}).status_code == 403


def test_admin_assigns_case_and_supervisor_closes_with_audit_report(
        durable_service, super_admin_headers):
    case_id = _open_case(durable_service)
    res = client.post(f"/api/v1/cases/{case_id}/assign", headers=super_admin_headers,
                      json={"staff_id": "sup_karim"})
    assert res.status_code == 200, res.text
    karim = _headers("sup_karim", "supervisor")
    mine = client.get("/api/v1/workdesk/cases?scope=mine", headers=karim).json()["cases"]
    assert [c["case_id"] for c in mine] == [case_id]

    note = client.post(f"/api/v1/cases/{case_id}/notes", headers=karim,
                       json={"note_type": "critical", "body": "Customer says agent kept 500."})
    assert note.status_code == 201
    report = client.post(f"/api/v1/cases/{case_id}/audit-report", headers=karim, json={
        "decision": "denied", "risk_level": "high", "customer_contacted": True,
        "findings": "Customer confirmed receiving 2500 instead of 3000.",
        "action_taken": "Agent placed on watchlist; refund requested.",
        "recommendation": "Field visit within 7 days."})
    assert report.status_code == 201, report.text

    file = client.get(f"/api/v1/cases/{case_id}/file", headers=karim).json()
    assert file["status"] == "denied" and file["closed_at"] and not file["can_act"]
    kinds = [n["note_type"] for n in file["notes_list"]]
    assert "critical" in kinds and "audit" in kinds
    assert file["reports"][0]["risk_level"] == "high"
    again = client.post(f"/api/v1/cases/{case_id}/audit-report", headers=karim, json={
        "decision": "approved", "risk_level": "low", "findings": "second report attempt",
        "action_taken": "none"})
    assert again.status_code == 409


def test_cannot_assign_to_non_supervisor(durable_service, super_admin_headers):
    case_id = _open_case(durable_service)
    res = client.post(f"/api/v1/cases/{case_id}/assign", headers=super_admin_headers,
                      json={"staff_id": "admin_777"})
    assert res.status_code == 409


def test_distribute_cases_spreads_evenly(durable_service, super_admin_headers):
    ids = [_open_case(durable_service) for _ in range(6)]
    res = client.post("/api/v1/cases/distribute", headers=super_admin_headers)
    assert res.status_code == 200 and res.json()["total"] == len(ids)
    counts = res.json()["assigned"].values()
    assert max(counts) - min(counts) <= 1


def test_staff_lifecycle_and_login(durable_service, super_admin_headers):
    res = client.post("/api/v1/admin/staff", headers=super_admin_headers, json={
        "staff_id": "sup_test", "display_name": "Test Supervisor", "role": "supervisor",
        "pin": "2468"})
    assert res.status_code == 201, res.text
    dup = client.post("/api/v1/admin/staff", headers=super_admin_headers, json={
        "staff_id": "sup_test", "display_name": "Again", "role": "supervisor", "pin": "2468"})
    assert dup.status_code == 409

    login = client.post("/api/v1/auth/demo-login", json={"principal": "sup_test", "pin": "2468"})
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "supervisor"
    assert login.json()["display_name"] == "Test Supervisor"
    bad = client.post("/api/v1/auth/demo-login", json={"principal": "sup_test", "pin": "0000"})
    assert bad.status_code == 401

    off = client.patch("/api/v1/admin/staff/sup_test", headers=super_admin_headers,
                       json={"active": False})
    assert off.status_code == 200 and off.json()["active"] is False
    assert client.post("/api/v1/auth/demo-login",
                       json={"principal": "sup_test", "pin": "2468"}).status_code == 401
    staff = client.get("/api/v1/admin/staff", headers=super_admin_headers).json()["items"]
    assert {"sup_nadia", "sup_karim", "sup_farzana", "supervisor_777"} <= {
        s["staff_id"] for s in staff}


def test_admin_cannot_deactivate_self(super_admin_headers):
    res = client.patch("/api/v1/admin/staff/admin_777", headers=super_admin_headers,
                       json={"active": False})
    assert res.status_code == 409


def test_admin_directories_paginate(durable_service, super_admin_headers):
    first = client.get("/api/v1/admin/users?limit=5", headers=super_admin_headers).json()
    assert len(first["items"]) == 5 and first["next_after"]
    second = client.get(f"/api/v1/admin/users?limit=5&after={first['next_after']}",
                        headers=super_admin_headers).json()
    assert not {u["user_id"] for u in first["items"]} & {u["user_id"] for u in second["items"]}
    found = client.get("/api/v1/admin/users?q=U_API", headers=super_admin_headers).json()
    assert found["items"] and all(u["user_id"].startswith("U_API") for u in found["items"])
    detail = client.get("/api/v1/admin/users/U_001", headers=super_admin_headers).json()
    assert detail["balance"] == 50000.0
    agents = client.get("/api/v1/admin/agents?q=A_00", headers=super_admin_headers).json()
    assert {a["agent_id"] for a in agents["items"]} >= {"A_001", "A_002"}
    txns = client.get("/api/v1/admin/transactions?include_future=true&limit=3",
                      headers=super_admin_headers).json()
    assert len(txns["items"]) == 3 and txns["next_before"]
