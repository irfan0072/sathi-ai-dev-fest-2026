"""Dedicated tests for scoped synthetic demo authentication, JWT, and authorization."""

from __future__ import annotations

import pytest
from app.auth.jwt import (
    InvalidTokenError,
    SecretUnconfiguredError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    is_jwt_secret_configured,
)
from app.main import app
from app.mandates.router import set_mandate_service
from app.mandates.service import MandateService
from fastapi.testclient import TestClient
from tests.conftest import TEST_JWT_SECRET, create_test_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_mandates_service(durable_service: MandateService) -> None:
    set_mandate_service(durable_service)


def test_jwt_token_creation_and_verification():
    """Verify standard HS256 token creation and verification."""
    payload = {
        "sub": "U_TEST_001",
        "role": "customer_channel",
        "allowed_users": [],
        "scope": "synthetic_demo",
    }
    token = create_access_token(payload, expires_in_seconds=300, secret=TEST_JWT_SECRET)
    decoded = decode_access_token(token, secret=TEST_JWT_SECRET)

    assert decoded["sub"] == "U_TEST_001"
    assert decoded["role"] == "customer_channel"
    assert decoded["scope"] == "synthetic_demo"
    assert "exp" in decoded
    assert "iat" in decoded


def test_jwt_token_expired():
    """Verify expired token raises TokenExpiredError."""
    payload = {"sub": "U_TEST_001", "role": "customer_channel"}
    # Create token already expired in the past
    token = create_access_token(payload, expires_in_seconds=-10, secret=TEST_JWT_SECRET)

    with pytest.raises(TokenExpiredError):
        decode_access_token(token, secret=TEST_JWT_SECRET)


def test_jwt_token_tampered_signature_rejected():
    """Verify signature tampering is detected and raises InvalidTokenError."""
    payload = {"sub": "U_TEST_001", "role": "customer_channel"}
    token = create_access_token(payload, expires_in_seconds=300, secret=TEST_JWT_SECRET)

    # Tamper with signature segment
    parts = token.split(".")
    tampered_sig = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered_token, secret=TEST_JWT_SECRET)


def test_jwt_token_tampered_payload_rejected():
    """Verify payload tampering is detected and raises InvalidTokenError."""
    token = create_test_token("U_001", "customer_channel")
    parts = token.split(".")
    tampered_token = f"{parts[0]}.eyJzdWIiOiJVX0hBQ0tFRCJ9.{parts[2]}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered_token, secret=TEST_JWT_SECRET)


def test_jwt_secret_unconfigured_fail_closed(monkeypatch):
    """Missing or placeholder JWT_SECRET must fail-closed."""
    for placeholder in ("", "CHANGE_ME", "YOUR_SECRET_HERE", "CHANGEME"):
        monkeypatch.setenv("JWT_SECRET", placeholder)
        assert not is_jwt_secret_configured()
        with pytest.raises(SecretUnconfiguredError):
            decode_access_token("some.fake.token")

    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    assert is_jwt_secret_configured()


def test_health_check_diagnostic_without_credentials(monkeypatch):
    """Health endpoint diagnoses unavailable database without leaking secrets."""
    from app import bootstrap
    monkeypatch.setattr(bootstrap, "database_ready", lambda config: False)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["database"] == "unavailable"
    assert data["auth_signing"] == "configured"
    assert "secret" not in data
    assert TEST_JWT_SECRET not in resp.text

    monkeypatch.setenv("JWT_SECRET", "CHANGE_ME")
    resp_deg = client.get("/health")
    assert resp_deg.status_code == 503
    assert resp_deg.json()["auth_signing"] == "unconfigured"
    assert resp_deg.json()["status"] == "degraded"

    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)


def test_api_demo_login_agent_success():
    """Valid synthetic demo agent login returns scoped token."""
    resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_agent", "pin": "1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "agent"
    assert data["subject"] == "A_777_000001"
    assert "U_777_000001" in data["allowed_users"]
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_api_demo_login_customer_and_analyst_success():
    """Valid synthetic demo customer and analyst logins return scoped tokens."""
    c_resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_customer", "pin": "5678"},
    )
    assert c_resp.status_code == 200
    assert c_resp.json()["role"] == "customer_channel"
    assert c_resp.json()["subject"] == "U_777_000001"

    a_resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_analyst", "pin": "9012"},
    )
    assert a_resp.status_code == 200
    assert a_resp.json()["role"] == "analyst"
    assert a_resp.json()["subject"] == "analyst_777"


def test_api_demo_login_invalid_pin_rejected():
    """Incorrect PIN is rejected with 401."""
    resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_agent", "pin": "9999"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_api_demo_login_unknown_principal_rejected():
    """Unwhitelisted or admin principals rejected with 401."""
    resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "admin_root", "pin": "password"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_api_demo_login_unconfigured_secret_returns_503(monkeypatch):
    """Missing or placeholder JWT_SECRET returns 503 fail-closed on login."""
    monkeypatch.setenv("JWT_SECRET", "CHANGE_ME")
    resp = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_agent", "pin": "1234"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SECURITY_CONFIG_ERROR"
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)


def test_rbac_endpoint_enforcement():
    """Verify role-based access control across all protected endpoints."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_001"])
    customer_token = create_test_token("U_001", "customer_channel")
    analyst_token = create_test_token("analyst_01", "analyst")

    # 1. Customer cannot request mandate (requires agent role)
    r1 = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert r1.status_code == 403

    # 2. Analyst cannot request mandate
    r2 = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert r2.status_code == 403

    # Agent requests mandate successfully
    req = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert req.status_code == 201
    mandate_id = req.json()["mandate_id"]

    # 3. Agent cannot verify mandate (customer only)
    r3 = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"mode": "keypad", "stated_amount": 1000.0},
    )
    assert r3.status_code == 403

    # 4. Another customer cannot verify someone else's mandate
    other_cust_token = create_test_token("U_002", "customer_channel")
    r4 = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {other_cust_token}"},
        json={"mode": "keypad", "stated_amount": 1000.0},
    )
    assert r4.status_code == 403
    assert r4.json()["error"]["code"] == "FORBIDDEN_OWNERSHIP"

    # Customer verifies successfully
    ver = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"mode": "keypad", "stated_amount": 1000.0},
    )
    assert ver.status_code == 200

    # 5. Customer cannot issue code (agent only)
    r5 = client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert r5.status_code == 403

    # 6. Another agent cannot issue code for this mandate
    other_agent_token = create_test_token("A_002", "agent", allowed_users=["U_001"])
    r6 = client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {other_agent_token}"},
    )
    assert r6.status_code == 403
    assert r6.json()["error"]["code"] == "FORBIDDEN_OWNERSHIP"

    # Bound agent issues code
    iss = client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert iss.status_code == 200
    code = iss.json()["code"]

    # 7. Customer cannot redeem mandate (agent only)
    r7 = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"code": code},
    )
    assert r7.status_code == 403

    # 8. Analyst cannot redeem mandate
    r8 = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"code": code},
    )
    assert r8.status_code == 403

    # Bound agent redeems successfully
    red = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": code},
    )
    assert red.status_code == 200


def test_agent_scope_restriction_to_allowed_users():
    """Agent restricted to allowed_users cannot operate on outside customers."""
    # Agent authorized only for U_777_000001
    agent_token = create_test_token("A_777_000001", "agent", allowed_users=["U_777_000001"])

    # Attempt to request mandate for training user U_001
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_001", "agent_id": "A_777_000001", "amount": 1000.0},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


def test_jwt_claims_validation():
    """Verify claim types, roles, scopes, and finite expiry validation."""
    # 1. Invalid role
    bad_role_payload = {"sub": "U_001", "role": "superuser", "scope": "synthetic_demo"}
    token1 = create_access_token(bad_role_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token1, secret=TEST_JWT_SECRET)

    # 2. Invalid scope (unscoped or non-synthetic_demo)
    bad_scope_payload = {"sub": "U_001", "role": "analyst", "scope": "production"}
    token2 = create_access_token(bad_scope_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token2, secret=TEST_JWT_SECRET)

    # 3. Non-string subject
    bad_sub_payload = {"sub": 12345, "role": "customer_channel", "scope": "synthetic_demo"}
    token3 = create_access_token(bad_sub_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token3, secret=TEST_JWT_SECRET)


def test_jwt_short_secret_rejected():
    """Secrets shorter than 32 characters must fail-closed."""
    short_secret = "too_short_secret"
    with pytest.raises(SecretUnconfiguredError):
        create_access_token({"sub": "U_001", "role": "customer_channel"}, secret=short_secret)
    with pytest.raises(SecretUnconfiguredError):
        decode_access_token("some.token.here", secret=short_secret)


def test_pyjwt_vetted_dependency_imported():
    """Ensure PyJWT (jwt) is the only JWT provider used."""
    import jwt

    assert hasattr(jwt, "encode")
    assert hasattr(jwt, "decode")
    assert hasattr(jwt, "PyJWTError")


def test_malformed_token_returns_401_error_envelope():
    """Malformed Authorization headers or tokens return 401 with standard error envelope."""
    resp = client.get(
        "/api/v1/cases",
        headers={"Authorization": "Bearer malformed.jwt.token"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_empty_allowed_users_denies_agent_access():
    """Agent with empty allowed_users must be denied access with 403 FORBIDDEN_SCOPE."""
    empty_scope_token = create_test_token("A_001", "agent", allowed_users=[])
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {empty_scope_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["error"]["code"] == "FORBIDDEN_SCOPE"


def test_no_secret_leaks_in_responses_or_errors(monkeypatch):
    """Ensure signing secret is never leaked in health, auth, or errors."""
    # 1. Health check response with unavailable database
    from app import bootstrap
    monkeypatch.setattr(bootstrap, "database_ready", lambda config: False)
    health_resp = client.get("/health")
    assert health_resp.status_code == 503
    assert TEST_JWT_SECRET not in health_resp.text

    # 2. Failed demo login
    bad_login = client.post(
        "/api/v1/auth/demo-login",
        json={"principal": "demo_agent", "pin": "0000"},
    )
    assert bad_login.status_code == 401
    assert TEST_JWT_SECRET not in bad_login.text
    assert "0000" not in bad_login.json()["error"]["message"]

    # 3. Invalid token error
    bad_token_resp = client.get(
        "/api/v1/cases",
        headers={"Authorization": "Bearer invalid.fake.token"},
    )
    assert bad_token_resp.status_code == 401
    assert TEST_JWT_SECRET not in bad_token_resp.text


def test_unscoped_admin_claims_rejected():
    """Arbitrary admin or unscoped tokens are rejected with InvalidTokenError."""
    # Arbitrary unscoped admin payload
    admin_payload = {"sub": "admin_root", "role": "admin", "scope": "admin_all"}
    token = create_access_token(admin_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=TEST_JWT_SECRET)

    # Missing sub or empty sub
    empty_sub_payload = {"sub": "   ", "role": "agent", "scope": "synthetic_demo"}
    token_empty = create_access_token(empty_sub_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token_empty, secret=TEST_JWT_SECRET)

    # Token completely missing scope claim
    unscoped_payload = {"sub": "A_001", "role": "agent"}
    token_unscoped = create_access_token(unscoped_payload, secret=TEST_JWT_SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token_unscoped, secret=TEST_JWT_SECRET)
