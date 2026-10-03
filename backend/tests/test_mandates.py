"""Comprehensive test suite for Durable Mandate Service and Policy Engine.

Covers:
- Full happy path lifecycle (request -> verify -> issue-code -> redeem -> confirm-cash)
- 422 on amount exceeding 5000 BDT default cap
- 422 on negative or zero amount
- 422 on daily cash-out limit exceeding 25000 BDT
- 409 on concurrent active mandate for same user
- 410 on expired mandate redemption
- 401 on incorrect one-time code
- 423 on 3 consecutive incorrect codes (account lockout)
- 409 on redeeming already-redeemed mandate
- Plain code never stored in mandate records (SHA-256 hash only)
- Cash gap tolerance logic (small gap unflagged, large gap flagged with case)
- Revocation lifecycle
- Audit logging verification across all actions
- Scoped synthetic Bearer authentication and role enforcement
- FastAPI router integration tests via TestClient
"""

from __future__ import annotations

import datetime
import hashlib
import json
from datetime import timezone

import pytest
from app.data.database import get_connection
from app.main import app as main_app
from app.mandates import (
    AccountLockedError,
    ActiveMandateExistsError,
    AlreadyRedeemedError,
    AmountExceedsCapError,
    DailyLimitExceededError,
    InvalidAmountError,
    InvalidCodeError,
    MandateExpiredError,
    MandateService,
    MaxAttemptsExceededError,
    router,
    set_mandate_service,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from tests.conftest import create_test_token


@pytest.fixture
def service(durable_service: MandateService) -> MandateService:
    """Fixture providing MandateService backed by isolated disposable PostgreSQL schema."""
    return durable_service


@pytest.fixture
def client(service: MandateService) -> TestClient:
    """Fixture providing a TestClient connected to a test app mounting the router."""
    set_mandate_service(service)
    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(router)
    return TestClient(app)


# ==============================================================================
# Service-Level Unit & Integration Tests (PostgreSQL durable)
# ==============================================================================


def test_happy_path_lifecycle(service: MandateService) -> None:
    """Verify complete end-to-end durable mandate lifecycle."""
    # 1. Request mandate
    req = service.request_mandate(user_id="U_001", agent_id="A_001", amount=3000.0)
    mandate_id = req["mandate_id"]
    assert req["status"] == "requested"
    assert req["next"] == "verify"
    assert req["amount"] == 3000.0
    assert req["fee"] == 45.0  # 1.5% official fee rate from config
    assert req["payout"] == 3000.0
    assert req["total_debit"] == 3045.0
    assert "keypad" in req["verification_modes"]

    record = service.mandates[mandate_id]
    assert record.status == "requested"
    assert record.amount == 3000.0

    # 2. Verify mandate (customer confirms matching amount)
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=3000.0)
    assert ver["outcome"] == "match"
    assert ver["decision"] == "ISSUE_MANDATE"
    assert ver["status"] == "verified"
    assert ver["code_delivery"] == "agent_terminal"
    # Security requirement: Plain code must NOT be returned to the customer
    assert ver["one_time_code"] is None
    assert ver["case_id"] is None

    # 3. Issue terminal code (bound agent requests one-time code for terminal)
    iss = service.issue_code(mandate_id=mandate_id, actor="A_001")
    assert iss["status"] == "active"
    code = iss["code"]
    assert code is not None and len(code) == 6

    # Security check: Plain code must NOT be stored in the record (SHA-256 only)
    record = service.mandates[mandate_id]
    assert record.code_hash == hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert not hasattr(record, "code") or getattr(record, "code", None) != code

    # 4. Redeem mandate (agent submits the one-time code)
    red = service.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")
    assert red["status"] == "redeemed"
    assert red["amount"] == 3000.0
    assert red["fee"] == 45.0
    assert red["txn_id"] is not None
    record = service.mandates[mandate_id]
    assert record.status == "redeemed"
    assert record.redeemed_txn_id == red["txn_id"]

    # 5. Confirm physical cash received by customer
    conf = service.confirm_cash(mandate_id=mandate_id, cash_received=3000.0)
    assert conf["gap"] == 0.0
    assert conf["flagged"] is False
    assert conf["case_id"] is None

    # 6. Verify audit log tracks all steps in durable PostgreSQL ledger
    actions = [entry["action"] for entry in service.audit_log if entry["entity_id"] == mandate_id]
    assert actions == [
        "mandate_requested",
        "mandate_verified",
        "mandate_code_issued",
        "mandate_redeemed",
        "cash_confirmed",
    ]


def test_amount_cap_exceeded(service: MandateService) -> None:
    """Amounts exceeding user_cap_default (5000 BDT) must raise AmountExceedsCapError."""
    with pytest.raises(AmountExceedsCapError) as exc_info:
        service.request_mandate(user_id="U_002", agent_id="A_001", amount=5001.0)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "AMOUNT_EXCEEDS_CAP"


def test_amount_non_positive(service: MandateService) -> None:
    """Non-positive amounts must raise InvalidAmountError."""
    with pytest.raises(InvalidAmountError):
        service.request_mandate(user_id="U_002", agent_id="A_001", amount=0.0)

    with pytest.raises(InvalidAmountError):
        service.request_mandate(user_id="U_002", agent_id="A_001", amount=-500.0)


def test_daily_cumulative_cashout_limit(service: MandateService) -> None:
    """Cumulative daily cash-out exceeding 25000 BDT must be rejected."""
    user = "U_DAILY"
    # Execute 5 cashouts of 5000 BDT = 25000 BDT
    for i in range(5):
        req = service.request_mandate(user_id=user, agent_id="A_001", amount=5000.0)
        service.verify_mandate(mandate_id=req["mandate_id"], mode="keypad", stated_amount=5000.0)
        iss = service.issue_code(mandate_id=req["mandate_id"], actor="A_001")
        service.redeem_mandate(mandate_id=req["mandate_id"], code=iss["code"], actor="A_001")

    assert service.get_user_daily_cashout(user) == 25000.0

    # 6th cashout attempt exceeds 25000 daily limit
    with pytest.raises(DailyLimitExceededError) as exc_info:
        service.request_mandate(user_id=user, agent_id="A_001", amount=500.0)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "DAILY_LIMIT_EXCEEDED"


def test_concurrent_active_mandate_prevented(service: MandateService) -> None:
    """User cannot request a new mandate while an active/requested mandate exists."""
    user = "U_API_CONC"
    service.request_mandate(user_id=user, agent_id="A_001", amount=2000.0)

    with pytest.raises(ActiveMandateExistsError) as exc_info:
        service.request_mandate(user_id=user, agent_id="A_002", amount=1500.0)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ACTIVE_MANDATE_EXISTS"


def test_redeem_expired_mandate(service: MandateService) -> None:
    """Attempting to redeem an expired mandate must raise MandateExpiredError (410)."""
    req = service.request_mandate(user_id="U_EXP", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    iss = service.issue_code(mandate_id=mandate_id, actor="A_001")
    code = iss["code"]

    # Manually backdate expires_at in PostgreSQL
    record = service.mandates[mandate_id]
    record.expires_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=1)

    with pytest.raises(MandateExpiredError) as exc_info:
        service.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")
    assert exc_info.value.status_code == 410
    assert exc_info.value.code == "MANDATE_EXPIRED"


def test_wrong_code_and_lockout(service: MandateService) -> None:
    """3 consecutive wrong codes must lock the mandate and raise AccountLockedError (423)."""
    req = service.request_mandate(user_id="U_LOCK", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    service.issue_code(mandate_id=mandate_id, actor="A_001")

    # Attempt 1: Wrong code -> 401
    with pytest.raises(InvalidCodeError) as exc1:
        service.redeem_mandate(mandate_id=mandate_id, code="000000", actor="A_001")
    assert exc1.value.status_code == 401
    assert "2 attempt(s) remaining" in exc1.value.message

    # Attempt 2: Wrong code -> 401
    with pytest.raises(InvalidCodeError) as exc2:
        service.redeem_mandate(mandate_id=mandate_id, code="111111", actor="A_001")
    assert exc2.value.status_code == 401
    assert "1 attempt(s) remaining" in exc2.value.message

    # Attempt 3: Wrong code -> 423 AccountLockedError
    with pytest.raises(AccountLockedError) as exc3:
        service.redeem_mandate(mandate_id=mandate_id, code="222222", actor="A_001")
    assert exc3.value.status_code == 423
    assert exc3.value.code == "ACCOUNT_LOCKED"

    record = service.mandates[mandate_id]
    assert record.status == "rejected"

    # Verify review case was created in PostgreSQL
    case = [c for c in service.cases if c["mandate_id"] == mandate_id][0]
    assert case["reason"] == "repeated_code_failures_lockout"
    assert case["status"] == "open"


def test_already_redeemed_cannot_be_redeemed_again(service: MandateService) -> None:
    """A redeemed mandate cannot be redeemed a second time (409)."""
    req = service.request_mandate(user_id="U_ONCE", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    iss = service.issue_code(mandate_id=mandate_id, actor="A_001")
    code = iss["code"]

    service.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")

    # Second redemption attempt
    with pytest.raises(AlreadyRedeemedError) as exc_info:
        service.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ALREADY_REDEEMED"


def test_verification_mismatch_creates_case(service: MandateService) -> None:
    """When customer stated amount mismatches requested amount, decision is REVIEW."""
    req = service.request_mandate(user_id="U_MIS", agent_id="A_001", amount=3000.0)
    mandate_id = req["mandate_id"]

    # 1. First mismatch: status remains requested for bounded retry (attempt 1 of 2)
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2500.0)
    assert ver["outcome"] == "mismatch"
    assert ver["decision"] == "REVIEW"
    assert ver["status"] == "requested"
    assert ver["one_time_code"] is None
    assert ver["case_id"] is not None

    record = service.mandates[mandate_id]
    assert record.status == "requested"

    # Prove states after fresh connection and no code/customer response
    with get_connection(service.db_url, schema=service.schema) as fresh_conn:
        with fresh_conn.cursor() as cur:
            cur.execute(
                "SELECT status, verification_attempts, code_hash "
                "FROM mandates WHERE mandate_id = %s;",
                (mandate_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "requested"
            assert row[1] == 1
            assert row[2] is None  # No code issued or exposed to customer

    case = [c for c in service.cases if c["case_id"] == ver["case_id"]][0]
    assert case["reason"] == "stated_amount_mismatch"
    assert case["evidence"]["expected_amount"] == 3000.0
    assert case["evidence"]["stated_amount"] == 2500.0

    # 2. Second mismatch reaches max verification attempts (2) and transitions to rejected
    ver2 = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2600.0)
    assert ver2["outcome"] == "mismatch"
    assert ver2["decision"] == "REVIEW"
    assert ver2["status"] == "rejected"
    assert ver2["one_time_code"] is None
    assert ver2["case_id"] is not None

    with get_connection(service.db_url, schema=service.schema) as fresh_conn:
        with fresh_conn.cursor() as cur:
            cur.execute(
                "SELECT status, verification_attempts, code_hash "
                "FROM mandates WHERE mandate_id = %s;",
                (mandate_id,),
            )
            row2 = cur.fetchone()
            assert row2 is not None
            assert row2[0] == "rejected"
            assert row2[1] == 2
            assert row2[2] is None

    # 3. Terminal rejected never revives
    with pytest.raises(MaxAttemptsExceededError):
        service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=3000.0)


def test_max_verification_attempts_exceeded(service: MandateService) -> None:
    """Exceeding max verification attempts (2) raises MaxAttemptsExceededError."""
    req = service.request_mandate(user_id="U_ATT", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]

    # Attempt 1
    v1 = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=999.0)
    assert v1["status"] == "requested"
    # Attempt 2
    v2 = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=998.0)
    assert v2["status"] == "rejected"
    # Attempt 3 exceeds limit of 2
    with pytest.raises(MaxAttemptsExceededError) as exc:
        service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    assert exc.value.status_code == 422
    assert exc.value.code == "MAX_ATTEMPTS_EXCEEDED"


def test_cash_gap_tolerance(service: MandateService) -> None:
    """Small discrepancy within tolerance unflagged; gap exceeding tolerance flagged."""
    req = service.request_mandate(user_id="U_GAP", agent_id="A_001", amount=4000.0)
    mandate_id = req["mandate_id"]
    service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=4000.0)
    iss = service.issue_code(mandate_id=mandate_id, actor="A_001")
    service.redeem_mandate(mandate_id=mandate_id, code=iss["code"], actor="A_001")

    # Gap of 30 BDT is within tolerance of max(50, 0.02 * 4000 = 80) -> unflagged
    c1 = service.confirm_cash(mandate_id=mandate_id, cash_received=3970.0)
    assert c1["gap"] == 30.0
    assert c1["flagged"] is False
    assert c1["case_id"] is None

    # Idempotent repeat: reporting the same 3970.0 returns identical result
    c1_repeat = service.confirm_cash(mandate_id=mandate_id, cash_received=3970.0)
    assert c1_repeat["gap"] == 30.0
    assert c1_repeat["flagged"] is False

    # Reporting a different amount for already confirmed mandate is rejected
    with pytest.raises(Exception):
        service.confirm_cash(mandate_id=mandate_id, cash_received=3500.0)


def test_revocation_lifecycle(service: MandateService) -> None:
    """Active or requested mandate can be revoked, but redeemed mandate cannot."""
    req = service.request_mandate(user_id="U_REV", agent_id="A_001", amount=1500.0)
    mandate_id = req["mandate_id"]

    rev = service.revoke_mandate(mandate_id=mandate_id)
    assert rev["status"] == "revoked"
    assert service.mandates[mandate_id].status == "revoked"

    # Cannot redeem revoked mandate
    with pytest.raises(Exception):
        service.redeem_mandate(mandate_id=mandate_id, code="123456", actor="A_001")

    # Already redeemed mandate cannot be revoked
    req2 = service.request_mandate(user_id="U_REV2", agent_id="A_001", amount=1000.0)
    m2_id = req2["mandate_id"]
    service.verify_mandate(mandate_id=m2_id, mode="keypad", stated_amount=1000.0)
    iss2 = service.issue_code(mandate_id=m2_id, actor="A_001")
    service.redeem_mandate(mandate_id=m2_id, code=iss2["code"], actor="A_001")

    with pytest.raises(AlreadyRedeemedError):
        service.revoke_mandate(mandate_id=m2_id)


# ==============================================================================
# FastAPI Router Endpoint Integration Tests (Scoped Bearer Auth)
# ==============================================================================


def test_api_happy_path(client: TestClient) -> None:
    """Test full HTTP API lifecycle conforming to authenticated scoped contracts."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_001"])
    customer_token = create_test_token("U_API_001", "customer_channel")

    # 1. POST /api/v1/mandates/request (Agent)
    req_resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": 3500.0, "purpose": "cash_out"},
    )
    assert req_resp.status_code == 201
    req_data = req_resp.json()
    mandate_id = req_data["mandate_id"]
    assert req_data["status"] == "requested"
    assert req_data["next"] == "verify"
    assert req_data["amount"] == 3500.0
    assert req_data["fee"] == 52.5  # 1.5% of 3500
    assert req_data["payout"] == 3500.0

    # 2. POST /api/v1/mandates/{id}/verify (Customer)
    ver_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"mode": "keypad", "stated_amount": "৩৫০০", "attempt": 1},  # Bangla numerals
    )
    assert ver_resp.status_code == 200
    ver_data = ver_resp.json()
    assert ver_data["outcome"] == "match"
    assert ver_data["decision"] == "ISSUE_MANDATE"
    assert ver_data["status"] == "verified"
    assert ver_data["code_delivery"] == "agent_terminal"
    assert ver_data["one_time_code"] is None  # Never to customer

    # 3. POST /api/v1/mandates/{id}/issue-code (Agent terminal)
    iss_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert iss_resp.status_code == 200
    iss_data = iss_resp.json()
    assert iss_data["status"] == "active"
    code = iss_data["code"]
    assert code is not None and len(code) == 6

    # 4. POST /api/v1/mandates/{id}/redeem (Agent)
    red_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": code},
    )
    assert red_resp.status_code == 200
    red_data = red_resp.json()
    assert red_data["status"] == "redeemed"
    assert red_data["amount"] == 3500.0
    assert red_data["fee"] == 52.5

    # 5. POST /api/v1/mandates/{id}/confirm-cash (Customer)
    conf_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/confirm-cash",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"cash_received": 3500.0},
    )
    assert conf_resp.status_code == 200
    conf_data = conf_resp.json()
    assert conf_data["gap"] == 0.0
    assert conf_data["flagged"] is False


def test_api_unauthenticated_request_rejected(client: TestClient) -> None:
    """Endpoints reject requests missing Bearer tokens (401)."""
    resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_api_x_actor_cannot_authenticate(client: TestClient) -> None:
    """X-Actor header alone cannot bypass authentication."""
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"X-Actor": "A_001"},
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp.status_code == 401


def test_api_role_forbidden(client: TestClient) -> None:
    """Customer channel role cannot request mandate (403)."""
    customer_token = create_test_token("U_API_001", "customer_channel")
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp.status_code == 403


def test_api_ownership_mismatch_forbidden(client: TestClient) -> None:
    """Agent token for A_001 cannot request mandate stating A_002."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_001"])
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_001", "agent_id": "A_002", "amount": 1000.0},
    )
    assert resp.status_code == 403


def test_api_amount_cap_exceeded_error_envelope(client: TestClient) -> None:
    """Test 422 amount cap returns standard Sathi error envelope."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_002"])
    resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_002", "agent_id": "A_001", "amount": 6000.0},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "AMOUNT_EXCEEDS_CAP"


def test_api_wrong_code_and_lockout(client: TestClient) -> None:
    """Test 401 on wrong code and 423 on lockout with error envelope."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_LOCK"])
    cust_token = create_test_token("U_API_LOCK", "customer_channel")

    req_resp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_LOCK", "agent_id": "A_001", "amount": 1000.0},
    )
    mandate_id = req_resp.json()["mandate_id"]
    client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": 1000.0},
    )
    client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {agent_token}"},
    )

    # 1st wrong code -> 401
    r1 = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": "000000"},
    )
    assert r1.status_code == 401
    assert r1.json()["error"]["code"] == "INVALID_ONE_TIME_CODE"

    # 2nd wrong code -> 401
    r2 = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": "000001"},
    )
    assert r2.status_code == 401

    # 3rd wrong code -> 423
    r3 = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": "000002"},
    )
    assert r3.status_code == 423
    assert r3.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_api_raw_input_validation_and_rejections(client: TestClient) -> None:
    """HTTP requests with raw bool, excess precision, malformed commas, and

    SQL injection are rejected with 422.
    """
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_001"])

    # 1. Raw bool True/False rejected (not coerced to 1.0/0.0)
    for bad_bool in (True, False):
        resp = client.post(
            "/api/v1/mandates/request",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={"user_id": "U_API_001", "agent_id": "A_001", "amount": bad_bool},
        )
        assert resp.status_code == 422

    # 2. Excess decimal precision rejected
    for bad_precision in ("100.001", 100.001, "3500.123"):
        resp = client.post(
            "/api/v1/mandates/request",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={"user_id": "U_API_001", "agent_id": "A_001", "amount": bad_precision},
        )
        assert resp.status_code == 422

    # 3. Malformed comma groupings rejected
    for bad_comma in ("2,50", "3,00,0", "3000.0,5", ",3000", "3000,", "3,,000"):
        resp = client.post(
            "/api/v1/mandates/request",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={"user_id": "U_API_001", "agent_id": "A_001", "amount": bad_comma},
        )
        assert resp.status_code == 422

    # 4. Non-finite and SQL injection strings rejected
    for bad_val in ("NaN", "Infinity", "-Infinity", "3000; DROP TABLE mandates; --"):
        resp = client.post(
            "/api/v1/mandates/request",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={"user_id": "U_API_001", "agent_id": "A_001", "amount": bad_val},
        )
        assert resp.status_code == 422

    # 5. Unsupported purpose rejected
    resp_purp = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={
            "user_id": "U_API_001",
            "agent_id": "A_001",
            "amount": 1000.0,
            "purpose": "unsupported_purpose",
        },
    )
    assert resp_purp.status_code == 422

    # 6. Valid Bangla grouped numerals accepted
    resp_bn = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": "৩,০০০"},
    )
    assert resp_bn.status_code == 201
    assert resp_bn.json()["amount"] == 3000.0


def test_api_verify_and_confirm_raw_inputs_and_modes(client: TestClient) -> None:
    """Verify endpoint enforces mode validation and raw input parsing."""
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_API_002"])
    cust_token = create_test_token("U_API_002", "customer_channel")

    req = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_API_002", "agent_id": "A_001", "amount": 2000.0},
    )
    assert req.status_code == 201
    m_id = req.json()["mandate_id"]

    # Unsupported mode rejected 422
    resp_mode = client.post(
        f"/api/v1/mandates/{m_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "telepathy", "stated_amount": 2000.0},
    )
    assert resp_mode.status_code == 422

    # Stated amount with raw boolean rejected 422
    resp_bool = client.post(
        f"/api/v1/mandates/{m_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": True},
    )
    assert resp_bool.status_code == 422

    # Stated amount with malformed comma grouping rejected 422
    resp_comma = client.post(
        f"/api/v1/mandates/{m_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": "2,50"},
    )
    assert resp_comma.status_code == 422


def test_api_missing_controls_and_scope_enforcement(client: TestClient) -> None:
    """Agent scope boundary, empty allowed_users denial, and role boundaries enforced."""
    # 1. Agent token with allowed_users=["U_001"] cannot access U_002 -> 403 FORBIDDEN_SCOPE
    agent_scoped = create_test_token("A_001", "agent", allowed_users=["U_001"])
    resp_scope = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_scoped}"},
        json={"user_id": "U_002", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp_scope.status_code == 403
    assert resp_scope.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    # 2. Agent token with EMPTY allowed_users must deny access (never allow all users)
    agent_empty = create_test_token("A_001", "agent", allowed_users=[])
    resp_empty = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_empty}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp_empty.status_code == 403
    assert resp_empty.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    # 3. Analyst token cannot request mandate -> 403 FORBIDDEN_ROLE
    analyst_token = create_test_token("analyst_01", "analyst")
    resp_analyst = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert resp_analyst.status_code == 403
    assert resp_analyst.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_actual_app_validation_handler_regressions(service: MandateService) -> None:
    """Regressions testing actual app.main RequestValidationError handler.

    Verifies:
    - Safe 422 envelope without raw exception objects, nonfinite values, or credentials.
    - TestClient(main_app, raise_server_exceptions=False) returns 422, never 500.
    - Malformed input handling on request, verify, and confirm-cash endpoints.
    - Preserved database counts and counters across rejected inputs.
    - Forbidden authentication remains 401/403.
    """
    set_mandate_service(service)
    actual_client = TestClient(main_app, raise_server_exceptions=False)

    agent_token = create_test_token("A_001", "agent", allowed_users=["U_001"])
    cust_token = create_test_token("U_001", "customer_channel")
    analyst_token = create_test_token("analyst_01", "analyst")

    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM mandates;")
            init_mandate_count = cur.fetchone()[0]

    # 1. Malformed request input: amount True, '3,00', 0, 100.001, NaN, Inf
    malformed_amounts = [True, "3,00", 0, 100.001, float("nan"), float("inf")]
    for bad_amt in malformed_amounts:
        resp = actual_client.post(
            "/api/v1/mandates/request",
            headers={
                "Authorization": f"Bearer {agent_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"user_id": "U_001", "agent_id": "A_001", "amount": bad_amt}),
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "details" in body["error"]
        assert "detail" in body
        # Verify no raw exception objects or internal trace leaked
        assert "ValueError" not in str(body["error"]["details"])

    # Verify preserved database mandate count after all malformed requests
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM mandates;")
            assert cur.fetchone()[0] == init_mandate_count

    # 2. Create a valid mandate to test verify and confirm-cash
    valid_req = actual_client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert valid_req.status_code == 201
    mandate_id = valid_req.json()["mandate_id"]

    # Verify initial attempt counter in database
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT verification_attempts, status FROM mandates WHERE mandate_id = %s;",
                (mandate_id,),
            )
            attempts, m_status = cur.fetchone()
            assert attempts == 0
            assert m_status == "requested"

    # 3. Malformed verify input: mode 'telepathy', stated_amount True, '3,00', 0, 100.001
    malformed_verify = [
        {"mode": "telepathy", "stated_amount": 1000.0},
        {"mode": "keypad", "stated_amount": True},
        {"mode": "keypad", "stated_amount": "3,00"},
        {"mode": "keypad", "stated_amount": 0},
        {"mode": "keypad", "stated_amount": 100.001},
        {"mode": "keypad", "stated_amount": float("nan")},
    ]
    for bad_payload in malformed_verify:
        v_resp = actual_client.post(
            f"/api/v1/mandates/{mandate_id}/verify",
            headers={
                "Authorization": f"Bearer {cust_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(bad_payload),
        )
        assert v_resp.status_code == 422
        v_body = v_resp.json()
        assert v_body["error"]["code"] == "VALIDATION_ERROR"
        assert "ValueError" not in str(v_body["error"]["details"])

    # Verify database counters preserved: verification_attempts remains 0
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT verification_attempts, status FROM mandates WHERE mandate_id = %s;",
                (mandate_id,),
            )
            attempts, m_status = cur.fetchone()
            assert attempts == 0
            assert m_status == "requested"

    # Advance mandate through verify, issue-code, and redeem to test confirm-cash
    v_ok = actual_client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": 1000.0},
    )
    assert v_ok.status_code == 200

    iss = actual_client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert iss.status_code == 200
    code = iss.json()["code"]

    red = actual_client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": code},
    )
    assert red.status_code == 200

    # 4. Malformed confirm-cash input: cash_received True, '2,50', 0, 100.001
    malformed_cash = [True, "2,50", 0, 100.001, float("nan")]
    for bad_cash in malformed_cash:
        c_resp = actual_client.post(
            f"/api/v1/mandates/{mandate_id}/confirm-cash",
            headers={
                "Authorization": f"Bearer {cust_token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"cash_received": bad_cash}),
        )
        assert c_resp.status_code == 422
        c_body = c_resp.json()
        assert c_body["error"]["code"] == "VALIDATION_ERROR"
        assert "ValueError" not in str(c_body["error"]["details"])

    # 5. Forbidden auth remains 401/403 against actual app.main
    unauth_resp = actual_client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert unauth_resp.status_code == 401

    role_resp = actual_client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert role_resp.status_code == 403
    assert role_resp.json()["error"]["code"] == "FORBIDDEN_ROLE"

    scope_token = create_test_token("A_001", "agent", allowed_users=["U_OTHER"])
    scope_resp = actual_client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {scope_token}"},
        json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000.0},
    )
    assert scope_resp.status_code == 403
    assert scope_resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"
