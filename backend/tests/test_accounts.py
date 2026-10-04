"""Registered test accounts: a super admin creates real customers and agents by phone number."""

from __future__ import annotations

import pytest
from app.accounts.service import registered_number
from app.main import app
from app.mandates.service import MandateService
from app.voice import router as voice_router
from app.voice.providers import PlacedCall
from app.voice.service import VoiceService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)


class _RecordingProvider:
    name = "twilio"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall:
        self.calls.append(to_number)
        return PlacedCall(provider_call_sid="CA-test", status="ringing")

    def validate_request(self, url, params, signature) -> bool:
        return False


def _create(headers, **body):
    return client.post("/api/v1/admin/accounts", headers=headers, json=body)


def _login(kind: str, phone: str, pin: str):
    return client.post("/api/v1/auth/demo-login",
                       json={"principal": phone, "pin": pin, "account_type": kind})


@pytest.fixture
def accounts(durable_service: MandateService, super_admin_headers):
    customer = _create(super_admin_headers, kind="customer", phone="+880 1712-345678",
                       display_name="Test Customer", pin="2468", opening_balance=10000)
    agent = _create(super_admin_headers, kind="agent", phone="01812345678",
                    display_name="Test Agent", pin="1357", region="sylhet")
    assert customer.status_code == 201 and agent.status_code == 201
    return customer.json(), agent.json()


def test_only_super_admin_creates_accounts(durable_service: MandateService):
    sup = {"Authorization": f"Bearer {create_test_token('sup_nadia', 'supervisor')}"}
    res = _create(sup, kind="customer", phone="01712345678", display_name="X Y", pin="1234")
    assert res.status_code == 403


def test_create_and_sign_in_with_phone(accounts, super_admin_headers):
    customer, agent = accounts
    assert customer["subject"] == "U_P_01712345678" and customer["balance"] == 10000.0
    assert agent["subject"] == "A_P_01812345678" and agent["region"] == "sylhet"

    assert _login("customer", "01712345678", "0000").status_code == 401
    assert _login("agent", "01712345678", "2468").status_code == 401  # not an agent
    session = _login("customer", "01712345678", "2468").json()
    assert session["role"] == "customer_channel" and session["subject"] == customer["subject"]
    assert session["display_name"] == "Test Customer"
    agent_session = _login("agent", "+8801812345678", "1357").json()
    assert agent_session["role"] == "agent"
    assert agent_session["allowed_users"] == [customer["subject"]]

    dup = _create(super_admin_headers, kind="customer", phone="01712345678",
                  display_name="Again", pin="1111")
    assert dup.status_code == 409
    bad = _create(super_admin_headers, kind="customer", phone="12345", display_name="Bad",
                  pin="1111")
    assert bad.status_code == 422

    listed = client.get("/api/v1/admin/accounts", headers=super_admin_headers).json()["items"]
    assert {a["subject"] for a in listed} == {customer["subject"], agent["subject"]}
    topped = client.post(f"/api/v1/admin/accounts/{customer['account_id']}/add-money",
                         headers=super_admin_headers, json={"amount": 500}).json()
    assert topped["balance"] == 10500.0

    off = client.patch(f"/api/v1/admin/accounts/{customer['account_id']}",
                       headers=super_admin_headers, json={"active": False})
    assert off.json()["active"] is False
    assert _login("customer", "01712345678", "2468").status_code == 401


def test_real_call_goes_to_registered_number(accounts, durable_service: MandateService):
    customer, agent = accounts
    # Synthetic wallets are never dialled; registered customers are.
    assert registered_number(durable_service.get_connection, "U_9_0000500") is None
    assert registered_number(durable_service.get_connection,
                             customer["subject"]) == "+8801712345678"

    provider = _RecordingProvider()
    voice_router.set_voice_service(
        VoiceService(durable_service, provider, "https://api.example.com", {}))
    try:
        token = _login("agent", "01812345678", "1357").json()["access_token"]
        res = client.post("/api/v1/cashouts", headers={"Authorization": f"Bearer {token}"},
                          json={"user_id": customer["subject"], "amount": 1000})
        assert res.status_code == 201, res.text
        assert provider.calls == ["+8801712345678"]
    finally:
        voice_router.set_voice_service(None)
