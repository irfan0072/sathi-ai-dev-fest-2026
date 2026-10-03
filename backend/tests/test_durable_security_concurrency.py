"""Dedicated PostgreSQL tests for restart persistence, concurrency, lockouts, TTL, and Dhaka caps.

All tests run strictly within isolated disposable schemas created by test_schema fixture,
never modifying or deleting real or development data.
"""

from __future__ import annotations

import concurrent.futures
import datetime
from datetime import timezone
from decimal import Decimal

import pytest
from app.data.database import get_connection
from app.mandates import (
    AccountLockedError,
    AlreadyRedeemedError,
    DailyLimitExceededError,
    InsufficientBalanceError,
    InvalidMandateStateError,
    MandateExpiredError,
    MandateService,
    MaxAttemptsExceededError,
)


def test_restart_persistence(test_db_url: str, test_schema: str) -> None:
    """Prove mandate states, attempts, and ledger records persist across complete restarts."""
    # 1. Create first service instance
    svc_1 = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc_1.request_mandate(user_id="U_001", agent_id="A_001", amount=2500.0)
    mandate_id = req["mandate_id"]
    assert req["status"] == "requested"

    # 2. Destroy service instance completely and instantiate a second service instance
    del svc_1
    svc_2 = MandateService(db_url=test_db_url, schema=test_schema)
    record_2 = svc_2.mandates.get(mandate_id)
    assert record_2 is not None
    assert record_2.status == "requested"
    assert record_2.amount == 2500.0
    assert record_2.code_hash == ""

    # Verify mandate on second instance
    ver = svc_2.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2500.0)
    assert ver["status"] == "verified"

    # 3. Destroy second instance and instantiate a third service instance
    del svc_2
    svc_3 = MandateService(db_url=test_db_url, schema=test_schema)
    record_3 = svc_3.mandates.get(mandate_id)
    assert record_3 is not None
    assert record_3.status == "verified"
    assert record_3.verification_attempts == 1

    # Issue code on third instance
    iss = svc_3.issue_code(mandate_id=mandate_id, actor="A_001")
    code = iss["code"]

    # 4. Destroy third instance and instantiate a fourth service instance
    del svc_3
    svc_4 = MandateService(db_url=test_db_url, schema=test_schema)
    record_4 = svc_4.mandates.get(mandate_id)
    assert record_4 is not None
    assert record_4.status == "active"
    assert len(record_4.code_hash) == 64

    # Redeem on fourth instance
    red = svc_4.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")
    assert red["status"] == "redeemed"
    txn_id = red["txn_id"]

    # 5. Destroy fourth instance and instantiate a fifth service instance
    del svc_4
    svc_5 = MandateService(db_url=test_db_url, schema=test_schema)
    record_5 = svc_5.mandates.get(mandate_id)
    assert record_5 is not None
    assert record_5.status == "redeemed"
    assert record_5.redeemed_txn_id == txn_id

    # Verify actual ledger transaction in PostgreSQL
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT amount, fee, balance_after FROM transactions WHERE txn_id = %s;",
                (txn_id,),
            )
            t_row = cur.fetchone()
            assert t_row is not None
            assert Decimal(str(t_row[0])) == Decimal("2500.00")
            assert Decimal(str(t_row[1])) == Decimal("37.50")


def test_lockout_persistence_and_commit_on_domain_error(
    test_db_url: str, test_schema: str
) -> None:
    """Failed redemption attempts, status changes, cases, and audit logs must commit on error."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_LOCK", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]
    svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    svc.issue_code(mandate_id=mandate_id, actor="A_001")

    # Attempt 1: wrong code -> raises InvalidCodeError (422)
    with pytest.raises(Exception):
        svc.redeem_mandate(mandate_id=mandate_id, code="999999", actor="A_001")

    # In a completely new service connection, attempts must be 1 (NOT rolled back!)
    del svc
    svc_chk1 = MandateService(db_url=test_db_url, schema=test_schema)
    rec1 = svc_chk1.mandates.get(mandate_id)
    assert rec1.redemption_attempts == 1
    assert rec1.status == "active"

    # Attempt 2: wrong code -> raises InvalidCodeError (422)
    with pytest.raises(Exception):
        svc_chk1.redeem_mandate(mandate_id=mandate_id, code="888888", actor="A_001")

    del svc_chk1
    svc_chk2 = MandateService(db_url=test_db_url, schema=test_schema)
    rec2 = svc_chk2.mandates.get(mandate_id)
    assert rec2.redemption_attempts == 2
    assert rec2.status == "active"

    # Attempt 3: 3rd wrong code -> triggers lockout! Raises AccountLockedError (423)
    with pytest.raises(AccountLockedError):
        svc_chk2.redeem_mandate(mandate_id=mandate_id, code="777777", actor="A_001")

    # Verify lockout persisted in DB: attempts == 3, status == 'rejected'
    del svc_chk2
    svc_chk3 = MandateService(db_url=test_db_url, schema=test_schema)
    rec3 = svc_chk3.mandates.get(mandate_id)
    assert rec3.redemption_attempts == 3
    assert rec3.status == "rejected"

    # Case exists in cases table
    cases = [c for c in svc_chk3.cases if c["mandate_id"] == mandate_id]
    assert len(cases) == 1
    assert cases[0]["reason"] == "repeated_code_failures_lockout"
    assert cases[0]["status"] == "open"

    # Audit log exists
    audit_actions = [e["action"] for e in svc_chk3.audit_log if e["entity_id"] == mandate_id]
    assert "mandate_redeem_failed" in audit_actions
    assert "mandate_locked" in audit_actions

    # Attempt 4: future redemption immediately denied with AccountLockedError
    with pytest.raises(AccountLockedError):
        svc_chk3.redeem_mandate(mandate_id=mandate_id, code="123456", actor="A_001")


def test_verification_mismatch_and_max_attempts_persistence(
    test_db_url: str, test_schema: str
) -> None:
    """Verification attempts persist in DB across restarts when MaxAttemptsExceeded is raised."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_ATT", agent_id="A_001", amount=1200.0)
    mandate_id = req["mandate_id"]

    # Mismatch 1: customer states 1000 instead of 1200
    res1 = svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    assert res1["outcome"] == "mismatch"
    assert res1["status"] == "requested"

    del svc
    svc2 = MandateService(db_url=test_db_url, schema=test_schema)
    rec2 = svc2.mandates.get(mandate_id)
    assert rec2.verification_attempts == 1
    assert rec2.status == res1["status"]

    # Mismatch 2: customer states 1100 instead of 1200
    res2 = svc2.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1100.0)
    assert res2["outcome"] == "mismatch"
    assert res2["status"] == "rejected"

    del svc2
    svc3 = MandateService(db_url=test_db_url, schema=test_schema)
    rec3 = svc3.mandates.get(mandate_id)
    assert rec3.verification_attempts == 2
    assert rec3.status == res2["status"]

    # Attempt 3: exceeds max attempts limit of 2 -> raises MaxAttemptsExceededError
    with pytest.raises(MaxAttemptsExceededError):
        svc3.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1200.0)

    del svc3
    svc4 = MandateService(db_url=test_db_url, schema=test_schema)
    rec4 = svc4.mandates.get(mandate_id)
    assert rec4.verification_attempts == 2
    assert rec4.status == "rejected"


def test_exact_ttl_boundary_and_no_extension_on_issue_code(
    test_db_url: str, test_schema: str
) -> None:
    """Exact TTL boundary marks mandate expired; /issue-code does not extend expiry."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_EXP", agent_id="A_001", amount=1000.0)
    mandate_id = req["mandate_id"]

    # Customer verifies: expires_at is set to now + 15 minutes
    ver = svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    verified_expires_at = datetime.datetime.fromisoformat(ver["expires_at"])

    # Issue code to terminal: expires_at must NOT be extended!
    iss = svc.issue_code(mandate_id=mandate_id, actor="A_001")
    code = iss["code"]
    code_expires_at = datetime.datetime.fromisoformat(iss["expires_at"])

    # Expiry must be identical
    assert code_expires_at == verified_expires_at

    # Check boundary: exactly at expires_at or after, redemption must fail with MandateExpiredError
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            # Set expires_at to 1 second in the past
            past_ts = datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=1)
            cur.execute(
                "UPDATE mandates SET expires_at = %s WHERE mandate_id = %s;",
                (past_ts, mandate_id),
            )
        conn.commit()

    with pytest.raises(MandateExpiredError):
        svc.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")

    # In DB, status is now expired and audit log commits
    record = svc.mandates.get(mandate_id)
    assert record.status == "expired"


def test_concurrent_redemption_race_condition(test_db_url: str, test_schema: str) -> None:
    """Concurrent attempts to redeem the same mandate: exactly one succeeds, the other gets 409."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_API_CONC", agent_id="A_001", amount=2000.0)
    mandate_id = req["mandate_id"]
    svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=2000.0)
    iss = svc.issue_code(mandate_id=mandate_id, actor="A_001")
    code = iss["code"]

    results = []
    errors = []

    def try_redeem():
        # Each thread uses its own MandateService and independent PostgreSQL connection
        thread_svc = MandateService(db_url=test_db_url, schema=test_schema)
        try:
            res = thread_svc.redeem_mandate(mandate_id=mandate_id, code=code, actor="A_001")
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_redeem)
        f2 = executor.submit(try_redeem)
        concurrent.futures.wait([f1, f2])

    # Exactly one succeeded and one failed with AlreadyRedeemedError (409)
    assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}"
    assert isinstance(errors[0], AlreadyRedeemedError)
    assert errors[0].status_code == 409

    # Verify transactions table has exactly ONE cash-out transaction for this mandate
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM transactions
                WHERE user_id = 'U_API_CONC' AND txn_type = 'cash_out';
                """
            )
            count = cur.fetchone()[0]
            assert count == 1, f"Expected 1 cash-out transaction, got {count}"


def test_concurrent_spending_insufficient_balance_denied(
    test_db_url: str, test_schema: str
) -> None:
    """User balance cannot be overspent by concurrent mandates;
    second redemption denied with 422.
    """
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    user_id = "U_API_CONC_BAL"

    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (
                    user_id, group_label, gender, age_band, region, urban_rural
                ) VALUES (%s, 'independent_urban', 'female', '26-40', 'dhaka', 'urban');
                """,
                (user_id,),
            )
            # Give user exactly 3,000 BDT
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id, txn_type, credit_source, amount, fee, balance_after, channel, ts
                ) VALUES (%s, 'credit', 'salary', 3000.00, 0.00, 3000.00, 'app', now());
                """,
                (user_id,),
            )
        conn.commit()

    # Mandate 1: 2000 BDT (+ 30 fee = 2030)
    req1 = svc.request_mandate(user_id=user_id, agent_id="A_001", amount=2000.0)
    m1_id = req1["mandate_id"]
    svc.verify_mandate(mandate_id=m1_id, mode="keypad", stated_amount=2000.0)
    iss1 = svc.issue_code(mandate_id=m1_id, actor="A_001")
    code1 = iss1["code"]

    # Successfully redeem Mandate 1: balance drops from 3000 to 970 BDT
    svc.redeem_mandate(mandate_id=m1_id, code=code1, actor="A_001")

    # Mandate 2: 2000 BDT (requires 2030 BDT, but balance is now only 970 BDT)
    req2 = svc.request_mandate(user_id=user_id, agent_id="A_001", amount=2000.0)
    m2_id = req2["mandate_id"]
    svc.verify_mandate(mandate_id=m2_id, mode="keypad", stated_amount=2000.0)
    iss2 = svc.issue_code(mandate_id=m2_id, actor="A_001")
    code2 = iss2["code"]

    # Redeeming Mandate 2 must fail with InsufficientBalanceError (422)
    with pytest.raises(InsufficientBalanceError) as exc_info:
        svc.redeem_mandate(mandate_id=m2_id, code=code2, actor="A_001")
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "INSUFFICIENT_BALANCE"

    # User balance in ledger must remain 970 BDT (never negative)
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance_after FROM transactions
                WHERE user_id = %s
                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                """,
                (user_id,),
            )
            bal = Decimal(str(cur.fetchone()[0]))
            assert bal == Decimal("970.00")


def test_asia_dhaka_daily_cashout_cap_boundary(test_db_url: str, test_schema: str) -> None:
    """Asia/Dhaka midnight calendar boundary: transactions from yesterday do not count."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    user_id = "U_DHAKA_TEST"

    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (
                    user_id, group_label, gender, age_band, region, urban_rural
                ) VALUES (%s, 'independent_urban', 'female', '26-40', 'dhaka', 'urban');
                """,
                (user_id,),
            )
            # Give user ample credit (100,000 BDT)
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id, txn_type, credit_source, amount, fee, balance_after, channel, ts
                ) VALUES (
                    %s, 'credit', 'salary', 100000.00, 0.00, 100000.00, 'app',
                    '2026-09-30T00:00:00Z'::timestamptz
                );
                """,
                (user_id,),
            )
            # Insert cash-out of 20,000 BDT yesterday (2 days ago)
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id, agent_id, txn_type, amount, fee, balance_after, channel, ts
                ) VALUES (%s, 'A_001', 'cash_out', 20000.00, 300.00, 79700.00, 'agent_initiated',
                          (now() AT TIME ZONE 'Asia/Dhaka' - interval '2 days')::timestamptz);
                """,
                (user_id,),
            )
        conn.commit()

    # Today's daily cash-out total in Dhaka time is currently 0.00 BDT
    assert svc.get_user_daily_cashout(user_id) == 0.00

    # Requesting 5,000 BDT today succeeds
    req1 = svc.request_mandate(user_id=user_id, agent_id="A_001", amount=5000.0)
    svc.verify_mandate(mandate_id=req1["mandate_id"], mode="keypad", stated_amount=5000.0)
    iss1 = svc.issue_code(mandate_id=req1["mandate_id"], actor="A_001")
    svc.redeem_mandate(mandate_id=req1["mandate_id"], code=iss1["code"], actor="A_001")

    # Today's daily total is now 5,000 BDT
    assert svc.get_user_daily_cashout(user_id) == 5000.00


def test_cash_confirmation_idempotency_and_changed_report_conflict(
    test_db_url: str, test_schema: str
) -> None:
    """Physical cash confirmation on redeemed mandates; repeat idempotent; changed rejected."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_GAP", agent_id="A_001", amount=3000.0)
    mandate_id = req["mandate_id"]

    # 1. Attempting cash confirmation before redemption is rejected (409)
    with pytest.raises(InvalidMandateStateError):
        svc.confirm_cash(mandate_id=mandate_id, cash_received=3000.0)

    svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=3000.0)
    iss = svc.issue_code(mandate_id=mandate_id, actor="A_001")
    svc.redeem_mandate(mandate_id=mandate_id, code=iss["code"], actor="A_001")

    # 2. First cash confirmation succeeds (gap 10 BDT is within tolerance max(50, 0.02*3000=60))
    conf1 = svc.confirm_cash(mandate_id=mandate_id, cash_received=2990.0)
    assert conf1["gap"] == 10.0
    assert conf1["flagged"] is False
    assert conf1["case_id"] is None

    # 3. Exact repeated report is idempotent: returns identical result without duplicate rows
    conf1_repeat = svc.confirm_cash(mandate_id=mandate_id, cash_received=2990.0)
    assert conf1_repeat["gap"] == 10.0
    assert conf1_repeat["flagged"] is False

    # Check database: exactly ONE confirmation event exists in verification_events table
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM verification_events
                WHERE mandate_id = %s AND cash_received_reported IS NOT NULL;
                """,
                (mandate_id,),
            )
            count = cur.fetchone()[0]
            assert count == 1, f"Expected 1 cash-confirmation event, got {count}"

    # 4. Altered report for already confirmed mandate is rejected with 409
    with pytest.raises(InvalidMandateStateError) as exc_info:
        svc.confirm_cash(mandate_id=mandate_id, cash_received=2500.0)
    assert exc_info.value.status_code == 409


def test_terminal_rejection_cannot_be_verified_or_revived(
    test_db_url: str, test_schema: str
) -> None:
    """A rejected terminal mandate must never become verified even if a later attempt matches."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    req = svc.request_mandate(user_id="U_ATT", agent_id="A_001", amount=1200.0)
    mandate_id = req["mandate_id"]

    # Mismatch 1: customer states 1000 instead of 1200
    res1 = svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1000.0)
    assert res1["outcome"] == "mismatch"

    # Mismatch 2: customer states 1100 instead of 1200 (terminal limit reached)
    res2 = svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1100.0)
    assert res2["outcome"] == "mismatch"

    # In DB, status is terminal 'rejected'
    rec = svc.mandates.get(mandate_id)
    assert rec.status == "rejected"
    assert rec.verification_attempts == 2

    # Later attempt with matching amount (1200.0) MUST fail closed with MaxAttemptsExceededError
    with pytest.raises(MaxAttemptsExceededError):
        svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=1200.0)

    # Status remains terminal 'rejected' (never verified!)
    rec_after = svc.mandates.get(mandate_id)
    assert rec_after.status == "rejected"
    assert rec_after.verification_attempts == 2


def test_expired_live_mandate_sweep_allows_replacement(
    test_db_url: str, test_schema: str
) -> None:
    """Expired live mandate transitions to expired during request sweep, unblocking new mandate."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    user_id = "U_EXP"
    agent_id = "A_001"

    # Request first mandate
    req1 = svc.request_mandate(user_id=user_id, agent_id=agent_id, amount=1000.0)
    m1_id = req1["mandate_id"]

    # Backdate expires_at for m1 to past
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            past_ts = datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=5)
            cur.execute(
                "UPDATE mandates SET expires_at = %s WHERE mandate_id = %s;",
                (past_ts, m1_id),
            )
        conn.commit()

    # Requesting a second mandate for the same user sweeps expired live rows and succeeds
    req2 = svc.request_mandate(user_id=user_id, agent_id=agent_id, amount=1500.0)
    m2_id = req2["mandate_id"]
    assert m2_id != m1_id
    assert req2["status"] == "requested"

    # Previous mandate m1 is now marked expired in database
    rec1 = svc.mandates.get(m1_id)
    assert rec1.status == "expired"

    # Verify audit log contains request_expiry_sweep
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM audit_log
                WHERE entity_id = %s AND action = 'mandate_expired';
                """,
                (m1_id,),
            )
            assert cur.fetchone()[0] >= 1


def test_daily_cashout_limit_rechecked_at_redemption_under_user_lock(
    test_db_url: str, test_schema: str
) -> None:
    """Cumulative daily limit is rechecked at redemption; intervening transactions reject it."""
    svc = MandateService(db_url=test_db_url, schema=test_schema)
    user_id = "U_DAILY"
    agent_id = "A_001"

    # 1. User requests mandate for 5,000 BDT (daily limit is 25,000 BDT)
    req = svc.request_mandate(user_id=user_id, agent_id=agent_id, amount=5000.0)
    mandate_id = req["mandate_id"]
    svc.verify_mandate(mandate_id=mandate_id, mode="keypad", stated_amount=5000.0)
    iss = svc.issue_code(mandate_id=mandate_id, actor=agent_id)
    code = iss["code"]

    # 2. Intervening cash-out transaction occurs today for 22,000 BDT
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transactions (
                    user_id, agent_id, txn_type, amount, fee, balance_after, channel, ts
                ) VALUES (%s, %s, 'cash_out', 22000.00, 330.00, 27670.00, 'agent_initiated',
                          now() AT TIME ZONE 'Asia/Dhaka');
                """,
                (user_id, agent_id),
            )
        conn.commit()

    # 3. Redeeming original 5,000 BDT mandate now reaches 27,000 > 25,000 limit -> raises error
    with pytest.raises(DailyLimitExceededError):
        svc.redeem_mandate(mandate_id=mandate_id, code=code, actor=agent_id)

    # 4. In DB, mandate was NOT redeemed and audit log recorded the limit violation
    rec = svc.mandates.get(mandate_id)
    assert rec.status != "redeemed"

    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM audit_log
                WHERE entity_id = %s AND action = 'mandate_redeem_daily_limit_exceeded';
                """,
                (mandate_id,),
            )
            assert cur.fetchone()[0] == 1
