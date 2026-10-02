"""Comprehensive test suite for Mandate Service and Policy Engine.

Covers:
- Full happy path lifecycle (request -> verify -> redeem -> confirm-cash)
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
- FastAPI router integration tests via TestClient
"""

from __future__ import annotations

import datetime
import hashlib
from datetime import timezone

import pytest
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
from fastapi.testclient import TestClient


@pytest.fixture
def service() -> MandateService:
    """Fixture providing a fresh isolated MandateService instance."""
    return MandateService()


@pytest.fixture
def client(service: MandateService) -> TestClient:
    """Fixture providing a TestClient connected to a test app mounting the router."""
    set_mandate_service(service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ==============================================================================
# Service-Level Unit Tests
# ==============================================================================


def test_happy_path_lifecycle(service: MandateService) -> None:
    """Verify complete end-to-end mandate lifecycle."""
    # 1. Request mandate
    req = service.request_mandate(user_id="U_001", agent_id="A_001", amount=3000.0)
    mandate_id = req["mandate_id"]
    assert req["status"] == "requested"
    assert req["next"] == "verify"
    assert "keypad" in req["verification_modes"]

    record = service.mandates[mandate_id]
    assert record.status == "requested"
    assert record.amount == 3000.0

    # 2. Verify mandate (customer confirms matching amount)
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=3000.0)
    assert ver["outcome"] == "match"
    assert ver["decision"] == "ISSUE_MANDATE"
    assert ver["status"] == "active"
    code = ver["one_time_code"]
    assert code is not None and len(code) == 6
    assert ver["case_id"] is None

    # Crucial security check: Plain code must NOT be stored in the record
    assert record.code_hash == hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert not hasattr(record, "code") or getattr(record, "code", None) != code

    # 3. Redeem mandate (agent submits the one-time code)
    red = service.redeem_mandate(mandate_id=mandate_id, code=code)
    assert red["status"] == "redeemed"
    assert red["amount"] == 3000.0
    assert red["fee"] == 0.0
    assert red["txn_id"] is not None
    assert record.status == "redeemed"
    assert record.redeemed_txn_id == red["txn_id"]

    # 4. Confirm physical cash received by customer
    conf = service.confirm_cash(mandate_id=mandate_id, cash_received=3000.0)
    assert conf["gap"] == 0.0
    assert conf["flagged"] is False
    assert conf["case_id"] is None

    # 5. Verify audit log tracks all 4 steps
    actions = [entry["action"] for entry in service.audit_log if entry["entity_id"] == mandate_id]
    assert actions == [
        "mandate_requested",
        "mandate_verified",
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
        ver = service.verify_mandate(
            mandate_id=req["mandate_id"], mode="keypad", stated_amount=5000.0
        )
        service.redeem_mandate(mandate_id=req["mandate_id"], code=ver["one_time_code"])

    assert service.get_user_daily_cashout(user) == 25000.0

    # 6th cashout attempt exceeds 25000 daily limit
    with pytest.raises(DailyLimitExceededError) as exc_info:
        service.request_mandate(user_id=user, agent_id="A_001", amount=500.0)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "DAILY_LIMIT_EXCEEDED"


def test_concurrent_active_mandate_prevented(service: MandateService) -> None:
    """User cannot request a new mandate while an active/requested mandate exists."""
    user = "U_CONCURRENT"
    service.request_mandate(user_id=user, agent_id="A_001", amount=2000.0)

    # Attempting second mandate for same user raises ActiveMandateExistsError
    with pytest.raises(ActiveMandateExistsError) as exc_info:
        service.request_mandate(user_id=user, agent_id="A_002", amount=1500.0)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ACTIVE_MANDATE_EXISTS"


def test_redeem_expired_mandate(service: MandateService) -> None:
    """Attempting to redeem an expired mandate must raise MandateExpiredError (410)."""
    req = service.request_mandate(user_id="U_EXP", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    code = ver["one_time_code"]

    # Manually backdate expires_at to the past
    record = service.mandates[mandate_id]
    record.expires_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=1)

    with pytest.raises(MandateExpiredError) as exc_info:
        service.redeem_mandate(mandate_id=mandate_id, code=code)
    assert exc_info.value.status_code == 410
    assert exc_info.value.code == "MANDATE_EXPIRED"


def test_wrong_code_and_lockout(service: MandateService) -> None:
    """3 consecutive wrong codes must lock the mandate and raise AccountLockedError (423)."""
    req = service.request_mandate(user_id="U_LOCK", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)

    # Attempt 1: Wrong code -> 401
    with pytest.raises(InvalidCodeError) as exc1:
        service.redeem_mandate(mandate_id=mandate_id, code="000000")
    assert exc1.value.status_code == 401
    assert "2 attempt(s) remaining" in exc1.value.message

    # Attempt 2: Wrong code -> 401
    with pytest.raises(InvalidCodeError) as exc2:
        service.redeem_mandate(mandate_id=mandate_id, code="111111")
    assert exc2.value.status_code == 401
    assert "1 attempt(s) remaining" in exc2.value.message

    # Attempt 3: Wrong code -> 423 AccountLockedError
    with pytest.raises(AccountLockedError) as exc3:
        service.redeem_mandate(mandate_id=mandate_id, code="222222")
    assert exc3.value.status_code == 423
    assert exc3.value.code == "ACCOUNT_LOCKED"

    record = service.mandates[mandate_id]
    assert record.status == "locked"

    # Verify review case was created
    case = [c for c in service.cases if c["mandate_id"] == mandate_id][0]
    assert case["reason"] == "repeated_code_failures_lockout"
    assert case["status"] == "open"


def test_already_redeemed_cannot_be_redeemed_again(service: MandateService) -> None:
    """A redeemed mandate cannot be redeemed a second time (409)."""
    req = service.request_mandate(user_id="U_ONCE", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    code = ver["one_time_code"]

    service.redeem_mandate(mandate_id=mandate_id, code=code)

    # Second redemption attempt
    with pytest.raises(AlreadyRedeemedError) as exc_info:
        service.redeem_mandate(mandate_id=mandate_id, code=code)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ALREADY_REDEEMED"


def test_verification_mismatch_creates_case(service: MandateService) -> None:
    """When customer stated amount mismatches requested amount, decision is REVIEW."""
    req = service.request_mandate(user_id="U_MIS", agent_id="A_001", amount=3000.0)
    mandate_id = req["mandate_id"]

    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2500.0)
    assert ver["outcome"] == "mismatch"
    assert ver["decision"] == "REVIEW"
    assert ver["status"] == "rejected"
    assert ver["one_time_code"] is None
    assert ver["case_id"] is not None

    record = service.mandates[mandate_id]
    assert record.status == "rejected"

    case = [c for c in service.cases if c["case_id"] == ver["case_id"]][0]
    assert case["reason"] == "stated_amount_mismatch"
    assert case["evidence"]["expected_amount"] == 3000.0
    assert case["evidence"]["stated_amount"] == 2500.0


def test_max_verification_attempts_exceeded(service: MandateService) -> None:
    """Exceeding max verification attempts (2) raises MaxAttemptsExceededError."""
    req = service.request_mandate(user_id="U_ATT", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]

    with pytest.raises(MaxAttemptsExceededError) as exc:
        service.verify_mandate(
            mandate_id=mandate_id, mode="keypad", stated_amount=1000.0, attempt=3
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "MAX_ATTEMPTS_EXCEEDED"


def test_cash_gap_tolerance(service: MandateService) -> None:
    """Small discrepancy within tolerance unflagged; gap exceeding tolerance flagged."""
    # Amount: 4000 BDT
    # Tolerance: max(50 BDT, 0.02 * 4000 = 80 BDT) = 80 BDT
    req = service.request_mandate(user_id="U_GAP", agent_id="A_001", amount=4000.0)
    mandate_id = req["mandate_id"]
    ver = service.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=4000.0)
    service.redeem_mandate(mandate_id=mandate_id, code=ver["one_time_code"])

    # Gap of 30 BDT is within tolerance of 80 BDT -> unflagged
    c1 = service.confirm_cash(mandate_id=mandate_id, cash_received=3970.0)
    assert c1["gap"] == 30.0
    assert c1["flagged"] is False
    assert c1["case_id"] is None

    # Gap of 200 BDT exceeds tolerance of 80 BDT -> flagged with review case
    c2 = service.confirm_cash(mandate_id=mandate_id, cash_received=3800.0)
    assert c2["gap"] == 200.0
    assert c2["flagged"] is True
    assert c2["case_id"] is not None

    case = [c for c in service.cases if c["case_id"] == c2["case_id"]][0]
    assert case["reason"] == "cash_gap_tolerance_exceeded"
    assert case["evidence"]["gap"] == 200.0


def test_revocation_lifecycle(service: MandateService) -> None:
    """Active or requested mandate can be revoked, but redeemed mandate cannot."""
    req = service.request_mandate(user_id="U_REV", agent_id="A_001", amount=1500.0)
    mandate_id = req["mandate_id"]

    rev = service.revoke_mandate(mandate_id=mandate_id)
    assert rev["status"] == "revoked"
    assert service.mandates[mandate_id].status == "revoked"

    # Cannot redeem revoked mandate
    with pytest.raises(Exception):
        service.redeem_mandate(mandate_id=mandate_id, code="123456")

    # Already redeemed mandate cannot be revoked
    req2 = service.request_mandate(user_id="U_REV2", agent_id="A_001", amount=1000.0)
    m2_id = req2["mandate_id"]
    v2 = service.verify_mandate(mandate_id=m2_id, mode="keypad", stated_amount=1000.0)
    service.redeem_mandate(mandate_id=m2_id, code=v2["one_time_code"])

    with pytest.raises(AlreadyRedeemedError):
        service.revoke_mandate(mandate_id=m2_id)


# ==============================================================================
# FastAPI Router Endpoint Integration Tests
# ==============================================================================


def test_api_happy_path(client: TestClient) -> None:
    """Test full HTTP API lifecycle conforming to docs/api-contracts.md."""
    # 1. POST /api/v1/mandates/request
    req_resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_001", "agent_id": "A_001", "amount": 3500.0, "purpose": "cash_out"},
    )
    assert req_resp.status_code == 201
    req_data = req_resp.json()
    mandate_id = req_data["mandate_id"]
    assert req_data["status"] == "requested"
    assert req_data["next"] == "verify"
    assert req_data["verification_modes"] == ["keypad", "voice"]

    # 2. POST /api/v1/mandates/{id}/verify
    ver_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        json={"mode": "keypad", "stated_amount": 3500.0, "attempt": 1},
    )
    assert ver_resp.status_code == 200
    ver_data = ver_resp.json()
    assert ver_data["outcome"] == "match"
    assert ver_data["decision"] == "ISSUE_MANDATE"
    assert ver_data["status"] == "active"
    code = ver_data["one_time_code"]
    assert code is not None

    # 3. POST /api/v1/mandates/{id}/redeem
    red_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        json={"code": code},
    )
    assert red_resp.status_code == 200
    red_data = red_resp.json()
    assert red_data["status"] == "redeemed"
    assert red_data["amount"] == 3500.0
    assert red_data["fee"] == 0.0

    # 4. POST /api/v1/mandates/{id}/confirm-cash
    conf_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/confirm-cash",
        json={"cash_received": 3500.0},
    )
    assert conf_resp.status_code == 200
    conf_data = conf_resp.json()
    assert conf_data["gap"] == 0.0
    assert conf_data["flagged"] is False


def test_api_amount_cap_exceeded_error_envelope(client: TestClient) -> None:
    """Test 422 amount cap returns standard Sathi error envelope."""
    resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_002", "agent_id": "A_001", "amount": 6000.0},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "AMOUNT_EXCEEDS_CAP"
    assert "exceeds mandate cap" in data["error"]["message"]


def test_api_concurrent_mandate_conflict(client: TestClient) -> None:
    """Test 409 conflict returns standard Sathi error envelope."""
    client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_CONC", "agent_id": "A_001", "amount": 2000.0},
    )
    resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_CONC", "agent_id": "A_002", "amount": 2000.0},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"]["code"] == "ACTIVE_MANDATE_EXISTS"


def test_api_wrong_code_and_lockout(client: TestClient) -> None:
    """Test 401 on wrong code and 423 on lockout with error envelope."""
    req_resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_LOCK", "agent_id": "A_001", "amount": 1000.0},
    )
    mandate_id = req_resp.json()["mandate_id"]
    client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        json={"mode": "keypad", "stated_amount": 1000.0},
    )

    # 1st wrong code -> 401
    r1 = client.post(f"/api/v1/mandates/{mandate_id}/redeem", json={"code": "000000"})
    assert r1.status_code == 401
    assert r1.json()["error"]["code"] == "INVALID_ONE_TIME_CODE"

    # 2nd wrong code -> 401
    r2 = client.post(f"/api/v1/mandates/{mandate_id}/redeem", json={"code": "000001"})
    assert r2.status_code == 401

    # 3rd wrong code -> 423
    r3 = client.post(f"/api/v1/mandates/{mandate_id}/redeem", json={"code": "000002"})
    assert r3.status_code == 423
    assert r3.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_api_confirm_cash_gap_anomaly(client: TestClient) -> None:
    """Test POST /confirm-cash with excessive gap flags discrepancy and returns case_id."""
    req_resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_GAP", "agent_id": "A_001", "amount": 3000.0},
    )
    mandate_id = req_resp.json()["mandate_id"]
    ver_resp = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        json={"mode": "keypad", "stated_amount": 3000.0},
    )
    code = ver_resp.json()["one_time_code"]
    client.post(f"/api/v1/mandates/{mandate_id}/redeem", json={"code": code})

    # Customer received only 2800 (gap = 200, exceeding max(50, 0.02 * 3000 = 60))
    resp = client.post(
        f"/api/v1/mandates/{mandate_id}/confirm-cash",
        json={"cash_received": 2800.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["gap"] == 200.0
    assert data["flagged"] is True
    assert data["case_id"] is not None


def test_api_revoke_mandate(client: TestClient) -> None:
    """Test POST /revoke successfully revokes mandate."""
    req_resp = client.post(
        "/api/v1/mandates/request",
        json={"user_id": "U_API_REV", "agent_id": "A_001", "amount": 2000.0},
    )
    mandate_id = req_resp.json()["mandate_id"]

    rev_resp = client.post(f"/api/v1/mandates/{mandate_id}/revoke")
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "revoked"
