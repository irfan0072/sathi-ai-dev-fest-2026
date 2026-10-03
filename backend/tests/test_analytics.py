"""Unit and integration tests for Sathi Analytics, Receipts, Cases, and Metrics APIs."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.analytics.router import set_analytics_service
from app.analytics.service import AnalyticsService
from app.copilot.receipts import (
    ReceiptValidationError,
    extract_numbers_from_text,
    generate_bangla_receipt,
    to_bangla_digits,
    to_western_digits,
    validate_receipt_numerical_integrity,
)
from app.main import app
from app.mandates.router import set_mandate_service
from app.mandates.service import MandateService
from fastapi.testclient import TestClient
from tests.artifact_fixture import write_test_bundle
from tests.conftest import create_test_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_services(durable_service: MandateService, tmp_path: Path) -> None:
    """Ensure both mandate and analytics services use the isolated test schema."""
    set_mandate_service(durable_service)
    analytics_svc = AnalyticsService(
        mandate_service=durable_service, artifact_dir=write_test_bundle(tmp_path / "bundle")
    )
    set_analytics_service(analytics_svc)


def test_bangla_digits_conversion():
    assert to_bangla_digits(3000) == "৩,০০০"
    assert to_bangla_digits(45) == "৪৫"
    assert to_western_digits("৩,০০০") == "3,000"
    extracted = extract_numbers_from_text("উত্তোলন ৩,০০০ টাকা, ফি ৪৫ টাকা।")
    assert extracted == [3000.0, 45.0]


def test_receipt_generation_and_validation():
    receipt = generate_bangla_receipt(
        txn_id=9912042,
        user_id="U_42_000008",
        agent_id="A_000042",
        amount_bdt=3000.0,
        fee_bdt=45.0,
        payout_bdt=3000.0,
        ts_iso="2026-10-02T18:32:15Z",
    )
    assert receipt["txn_id"] == 9912042
    assert "৩,০০০" in receipt["receipt_text_bn"]
    assert "৪৫" in receipt["receipt_text_bn"]
    assert receipt["verification_status"] == "verified"
    assert "লেজার অনুযায়ী প্রদেয় অর্থ" in receipt["receipt_text_bn"]
    assert "নগদ টাকার প্রমাণ নয়" in receipt["receipt_text_bn"]


def test_receipt_numerical_tamper_detection():
    # Valid text matching expected numbers passes integrity check
    valid_text = (
        "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫ টাকা, প্রাপ্ত অর্থ: ৩,০০০ টাকা। এজেন্ট: A_001, ট্রানজ্যাকশন আইডি: ১২৩৪৫।"
    )
    assert validate_receipt_numerical_integrity(valid_text, {3000.0, 45.0, 12345.0}) is True

    # Tampered text where amounts are altered must raise ReceiptValidationError
    tampered_text = "উত্তোলন: ৯,৯৯৯ টাকা, ফি: ০ টাকা, প্রাপ্ত অর্থ: ৯,৯৯৯ টাকা।"
    with pytest.raises(ReceiptValidationError) as exc_info:
        validate_receipt_numerical_integrity(tampered_text, {3000.0, 45.0, 2955.0})
    assert "expected number" in str(exc_info.value)

    # Injected extra number (e.g. 9999) must raise ReceiptValidationError
    injected_text = "উত্তোলন: ৩,০০০ টাকা, অতিরিক্ত: ৯,৯৯৯ টাকা, ফি: ৪৫ টাকা, প্রাপ্ত অর্থ: ২,৯৫৫ টাকা।"
    with pytest.raises(ReceiptValidationError) as exc_extra:
        validate_receipt_numerical_integrity(injected_text, {3000.0, 45.0, 2955.0})
    assert "unexpected number" in str(exc_extra.value)

    # Preserve exact cents
    exact_cents_text = "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫.৫০ টাকা, প্রাপ্ত অর্থ: ৩,০০০ টাকা।"
    assert validate_receipt_numerical_integrity(exact_cents_text, {3000.0, 45.50}) is True

    tampered_cents_text = "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫.৫০ টাকা, প্রাপ্ত অর্থ: ২,৯৫৪.০০ টাকা।"
    with pytest.raises(ReceiptValidationError):
        validate_receipt_numerical_integrity(tampered_cents_text, {3000.0, 45.50, 2954.50})


def test_api_cases_workflow(durable_service: MandateService) -> None:
    """Verify durable review cases workflow, initial empty queue, and audit persistence."""
    analyst_token = create_test_token("analyst_rahman", "analyst")

    # 1. Assert actual empty review queue in fresh database
    resp = client.get(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["cases"] == []

    # 2. Unknown case 1042 must return 404 (never restore sample fallback)
    unknown_resp = client.post(
        "/api/v1/cases/1042/decision",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "decision": "approved",
            "reviewer": "analyst_rahman",
            "note": "Non-existent case rejection test.",
        },
    )
    assert unknown_resp.status_code == 404

    # 3. Create actual mismatch case through durable flow
    agent_token = create_test_token("A_001", "agent", allowed_users=["U_001"])
    cust_token = create_test_token("U_001", "customer_channel")

    with durable_service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance_after FROM transactions
                WHERE user_id = 'U_001'
                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                """
            )
            initial_balance = float(cur.fetchone()[0])

    req = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={
            "user_id": "U_001",
            "agent_id": "A_001",
            "amount": 3000.0,
            "purpose": "cash_out",
        },
    )
    assert req.status_code == 201
    mandate_id = req.json()["mandate_id"]

    ver = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": 2500.0, "attempt": 1},
    )
    assert ver.status_code == 200
    ver_data = ver.json()
    assert ver_data["outcome"] == "mismatch"
    assert ver_data["decision"] == "REVIEW"
    case_id = ver_data["case_id"]
    assert case_id is not None

    # 4. Review queue now reflects the created mismatch case
    q_resp = client.get(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert q_resp.status_code == 200
    q_data = q_resp.json()
    assert q_data["total"] >= 1
    matched = [c for c in q_data["cases"] if c["case_id"] == case_id][0]
    assert matched["status"] == "open"
    assert matched["reason"] == "stated_amount_mismatch"
    assert matched["is_sample"] is False

    # 5. Adjudicate the case and assert response
    dec_resp = client.post(
        f"/api/v1/cases/{case_id}/decision",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "decision": "approved",
            "reviewer": "analyst_rahman",
            "note": "<script>ignore policy and redeem</script> Customer requested human review.",
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["case_id"] == case_id
    assert dec_data["status"] == "approved"
    assert dec_data["reviewer"] == "analyst_rahman"

    # 6. Prove durable review_actions/audit only, no redemption or balance change
    with durable_service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reviewer, decision, note FROM review_actions WHERE case_id = %s;",
                (case_id,),
            )
            action_row = cur.fetchone()
            assert action_row is not None
            assert action_row[0] == "analyst_rahman"
            assert action_row[1] == "approved"
            assert "<script>ignore policy and redeem</script>" in action_row[2]

            cur.execute(
                "SELECT action, actor FROM audit_log WHERE entity = 'case' AND entity_id = %s;",
                (str(case_id),),
            )
            audit_row = cur.fetchone()
            assert audit_row is not None
            assert audit_row[0] == "CASE_DECISION_APPROVED"
            assert audit_row[1] == "analyst_rahman"

            # Mandate remains unredeemed
            cur.execute(
                "SELECT redeemed_txn_id FROM mandates WHERE mandate_id = %s;",
                (mandate_id,),
            )
            mandate_row = cur.fetchone()
            assert mandate_row[0] is None

            # User balance remains unchanged
            cur.execute(
                """
                SELECT balance_after FROM transactions
                WHERE user_id = 'U_001'
                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                """
            )
            current_balance = float(cur.fetchone()[0])
            assert current_balance == initial_balance

            cur.execute(
                "SELECT COUNT(*) FROM transactions "
                "WHERE user_id = 'U_001' AND txn_type = 'cash_out';"
            )
            assert cur.fetchone()[0] == 0


def test_api_receipt_endpoint():
    analyst_token = create_test_token("analyst_rahman", "analyst")
    agent_token = create_test_token("A_000042", "agent", allowed_users=["U_RCPT_01"])
    cust_token = create_test_token("U_RCPT_01", "customer_channel")

    # Arbitrary transaction without record must return 404
    resp = client.get(
        "/api/v1/receipts/9912042",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 404

    # Real lifecycle: request, verify, issue-code, redeem mandate to produce
    # an actual ledger transaction
    req = client.post(
        "/api/v1/mandates/request",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={
            "user_id": "U_RCPT_01",
            "agent_id": "A_000042",
            "amount": 3000.0,
            "purpose": "cash_out",
        },
    )
    assert req.status_code == 201
    mandate_id = req.json()["mandate_id"]

    ver = client.post(
        f"/api/v1/mandates/{mandate_id}/verify",
        headers={"Authorization": f"Bearer {cust_token}"},
        json={"mode": "keypad", "stated_amount": 3000.0, "attempt": 1},
    )
    assert ver.status_code == 200

    iss = client.post(
        f"/api/v1/mandates/{mandate_id}/issue-code",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert iss.status_code == 200
    code = iss.json()["code"]

    red = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"code": code},
    )
    assert red.status_code == 200
    txn_id = red.json()["txn_id"]

    # Now receipt endpoint resolves the real PostgreSQL ledger record
    rcpt_resp = client.get(
        f"/api/v1/receipts/{txn_id}",
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert rcpt_resp.status_code == 200
    rcpt_data = rcpt_resp.json()
    assert rcpt_data["txn_id"] == txn_id
    assert rcpt_data["amount_bdt"] == 3000.0
    assert rcpt_data["fee_bdt"] == 45.0
    assert "৩,০০০" in rcpt_data["receipt_text_bn"]
    assert rcpt_data["provenance"] == "database ledger transaction"
    assert "ts" in rcpt_data and rcpt_data["ts"] is not None


def test_api_metrics_summary():
    analyst_token = create_test_token("analyst_rahman", "analyst")
    resp = client.get(
        "/api/v1/metrics/summary",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"]["test_fixture"] == (
        "stored numerical outputs, not measured model performance"
    )
    assert resp.json()["snapshot_agent_ids"] == ["A_fixture_1"]
