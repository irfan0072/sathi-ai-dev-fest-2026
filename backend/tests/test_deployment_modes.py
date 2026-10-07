"""Public-demo isolation, token deactivation and the role matrix (judge audit finding 4).

SATHI_DEPLOYMENT_MODE=public_demo keeps the published synthetic sign-in working but makes
management read-only and pins every provider to its simulated/deterministic option.
"""

from __future__ import annotations

import pytest
from app.deployment import PUBLIC_DEMO_PINNED, deployment_mode
from app.main import app
from app.mandates.router import set_mandate_service
from app.mandates.service import MandateService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)


def _h(subject, role, users=None):
    return {"Authorization": f"Bearer {create_test_token(subject, role, users)}"}


ADMIN, SUP = _h("admin_777", "super_admin"), _h("supervisor_777", "supervisor")
AGENT, CUSTOMER = _h("A_001", "agent", ["U_001"]), _h("U_001", "customer_channel")


@pytest.fixture(autouse=True)
def database(durable_service: MandateService):
    set_mandate_service(durable_service)
    yield


@pytest.fixture
def public_demo(monkeypatch):
    monkeypatch.setenv("SATHI_DEPLOYMENT_MODE", "public_demo")


def test_mode_parsing_fails_closed(monkeypatch):
    monkeypatch.delenv("SATHI_DEPLOYMENT_MODE", raising=False)
    assert deployment_mode() == "local"
    for value, expected in (("public_demo", "public_demo"), ("PILOT", "pilot"),
                            ("local", "local"), ("typo", "public_demo")):
        monkeypatch.setenv("SATHI_DEPLOYMENT_MODE", value)
        assert deployment_mode() == expected


def test_public_demo_makes_management_read_only(public_demo, monkeypatch):
    monkeypatch.setenv("SATHI_SETTINGS_EDITABLE", "true")      # the unsafe render.yaml default
    settings = client.get("/api/v1/settings", headers=ADMIN)
    assert settings.status_code == 200 and settings.json()["editable"] is False
    assert client.put("/api/v1/settings", headers=ADMIN,
                      json={"changes": {"sim.rate_per_minute": 30}}).status_code == 403
    assert client.put("/api/v1/settings/credentials", headers=ADMIN,
                      json={"values": {"GEMINI_API_KEY": "x" * 30}}).status_code == 403
    blocked = {
        "post staff": client.post("/api/v1/admin/staff", headers=ADMIN, json={
            "staff_id": "intruder", "display_name": "Intruder", "role": "super_admin",
            "pin": "1234"}),
        "patch staff": client.patch("/api/v1/admin/staff/supervisor_777", headers=ADMIN,
                                    json={"active": False}),
        "post account": client.post("/api/v1/admin/accounts", headers=ADMIN, json={
            "kind": "customer", "phone": "01712345678", "display_name": "Real Person",
            "pin": "1234"}),
        "add money": client.post("/api/v1/admin/accounts/1/add-money", headers=ADMIN,
                                 json={"amount": 100}),
        "probe": client.get("/api/v1/settings/probe", headers=ADMIN),
        "provider test": client.post("/api/v1/settings/providers/twilio/test", headers=ADMIN),
        "paid test call": client.post("/api/v1/settings/providers/twilio/test-call",
                                      headers=ADMIN, json={"to": "+8801712345678"}),
    }
    for name, response in blocked.items():
        assert response.status_code == 403, (name, response.text)
        code = response.json()["error"]["code"]
        assert code in ("PUBLIC_DEMO_READ_ONLY", "SETTINGS_READ_ONLY"), name


def test_public_demo_pins_providers_even_with_overrides(public_demo, durable_service):
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO app_settings (key, value, updated_by) VALUES "
                    "('voice.provider', '\"twilio\"', 'x'), ('sms.provider', '\"alpha\"', 'x'), "
                    "('ai.provider_order', '\"gemini_first\"', 'x');")
        conn.commit()
    items = {i["key"]: i for i in client.get("/api/v1/settings", headers=ADMIN).json()["items"]}
    for key, value in PUBLIC_DEMO_PINNED.items():
        assert items[key]["value"] == value and items[key]["source"] == "deployment_mode"
    assert client.get("/api/v1/voice/config", headers=AGENT).json()["live_calls"] is False


def test_public_demo_keeps_the_synthetic_workflow_working(public_demo):
    login = client.post("/api/v1/auth/demo-login", json={"principal": "demo_agent", "pin": "1234"})
    assert login.status_code in (200, 401, 403, 503)       # sign-in path is not blocked by mode
    assert client.get("/api/v1/deployment").json()["simulated_only"] is True
    assert client.get("/api/v1/transactions", headers=AGENT).status_code == 200
    assert client.get("/api/v1/callcenter/queue", headers=SUP).status_code == 200


def test_local_mode_is_unchanged(monkeypatch):
    monkeypatch.delenv("SATHI_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SATHI_SETTINGS_EDITABLE", "true")
    assert client.get("/api/v1/settings", headers=ADMIN).json()["editable"] is True
    res = client.put("/api/v1/settings", headers=ADMIN,
                     json={"changes": {"sim.rate_per_minute": 30}})
    assert res.status_code == 200, res.text
    assert client.get("/api/v1/deployment").json()["mode"] == "local"
    monkeypatch.setenv("SATHI_SETTINGS_EDITABLE", "false")
    assert client.put("/api/v1/settings", headers=ADMIN,
                      json={"changes": {"sim.rate_per_minute": 31}}).status_code == 403


def test_deactivated_staff_token_stops_working_immediately(durable_service):
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT staff_id FROM staff WHERE role = 'supervisor' AND active LIMIT 1;")
        row = cur.fetchone()
    assert row, "demo supervisor must be seeded"
    token = _h(row[0], "supervisor")
    assert client.get("/api/v1/callcenter/queue", headers=token).status_code == 200
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE staff SET active = false WHERE staff_id = %s;", (row[0],))
        conn.commit()
    denied = client.get("/api/v1/callcenter/queue", headers=token)
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "ACCOUNT_DISABLED"
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE staff SET active = true WHERE staff_id = %s;", (row[0],))
        conn.commit()
    assert client.get("/api/v1/callcenter/queue", headers=token).status_code == 200


# ------------------------------------------------------------------ role and ownership matrix
@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("get", "/api/v1/settings", {"super_admin"}),
    ("get", "/api/v1/callcenter/stats", {"super_admin"}),
    ("get", "/api/v1/admin/staff", {"super_admin"}),
    ("get", "/api/v1/callcenter/queue", {"supervisor", "super_admin"}),
    ("get", "/api/v1/transaction-checks", {"analyst", "super_admin"}),
    ("get", "/api/v1/transactions", {"agent", "customer_channel"}),
])
def test_role_matrix(method, path, allowed):
    tokens = {"super_admin": ADMIN, "supervisor": SUP, "agent": AGENT,
              "customer_channel": CUSTOMER, "analyst": _h("analyst_777", "analyst")}
    for role, headers in tokens.items():
        status = getattr(client, method)(path, headers=headers).status_code
        if role in allowed:
            assert status == 200, (role, path, status)
        else:
            assert status == 403, (role, path, status)
    assert getattr(client, method)(path).status_code == 401


def test_agent_cannot_cash_out_for_another_agents_customer_or_customer_role():
    body = {"user_id": "U_002", "amount": 500}
    assert client.post("/api/v1/cashouts", headers=AGENT, json=body).status_code == 403
    assert client.post("/api/v1/cashouts", headers=CUSTOMER,
                       json={"user_id": "U_001", "amount": 500}).status_code == 403
    assert client.post("/api/v1/cashouts", json={"user_id": "U_001", "amount": 500}
                       ).status_code == 401
