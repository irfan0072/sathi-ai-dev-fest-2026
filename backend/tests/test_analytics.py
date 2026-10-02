"""Unit and integration tests for Sathi Analytics, Receipts, Cases, and Metrics APIs."""

import pytest
from app.copilot.receipts import (
    ReceiptValidationError,
    extract_numbers_from_text,
    generate_bangla_receipt,
    to_bangla_digits,
    to_western_digits,
    validate_receipt_numerical_integrity,
)
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


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
        payout_bdt=2955.0,
        ts_iso="2026-10-02T18:32:15Z",
    )
    assert receipt["txn_id"] == 9912042
    assert "৩,০০০" in receipt["receipt_text_bn"]
    assert "৪৫" in receipt["receipt_text_bn"]
    assert "২,৯৫৫" in receipt["receipt_text_bn"]
    assert receipt["verification_status"] == "verified"
    assert receipt["provenance"] == "runtime memory, not a database record"


def test_receipt_numerical_tamper_detection():
    # Valid text matching expected numbers passes integrity check
    valid_text = "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫ টাকা, প্রাপ্ত অর্থ: ২,৯৫৫ টাকা।"
    assert validate_receipt_numerical_integrity(valid_text, {3000.0, 45.0, 2955.0}) is True

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
    exact_cents_text = "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫.৫০ টাকা, প্রাপ্ত অর্থ: ২,৯৫৪.৫০ টাকা।"
    assert (
        validate_receipt_numerical_integrity(exact_cents_text, {3000.0, 45.50, 2954.50})
        is True
    )

    tampered_cents_text = "উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫.৫০ টাকা, প্রাপ্ত অর্থ: ২,৯৫৪.০০ টাকা।"
    with pytest.raises(ReceiptValidationError):
        validate_receipt_numerical_integrity(tampered_cents_text, {3000.0, 45.50, 2954.50})


def test_api_user_assisted_score():
    resp = client.get("/api/v1/users/U_42_000008/assisted-score")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "U_42_000008"
    assert data["provenance"] == "illustrative sample, not a result"
    assert data["is_sample"] is True
    assert len(data["top_reasons"]) > 0
    assert "feature" in data["top_reasons"][0]
    assert "display_name" in data["top_reasons"][0]


def test_api_agent_risk():
    resp = client.get("/api/v1/agents/A_000015/risk")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "A_000015"
    assert data["provenance"] == "illustrative sample, not a result"
    assert data["is_sample"] is True
    assert len(data["reasons"]) > 0
    assert "chittagong" not in data.get("peer_group", "").lower()


def test_api_outreach_list():
    resp = client.get("/api/v1/outreach")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"] == "illustrative sample, not a result"
    assert data["is_sample"] is True
    assert data["total"] >= 1
    assert data["items"][0]["provenance"] == "illustrative sample, not a result"


def test_api_cases_workflow():
    resp = client.get("/api/v1/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    case = data["cases"][0]
    case_id = case["case_id"]
    if case.get("is_sample"):
        assert case["provenance"] == "illustrative sample, not a result"

    dec_resp = client.post(
        f"/api/v1/cases/{case_id}/decision",
        json={
            "decision": "approved",
            "reviewer": "analyst_rahman",
            "note": "Verified customer biometric and audio recording.",
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["case_id"] == case_id
    assert dec_data["status"] == "approved"
    assert dec_data["reviewer"] == "analyst_rahman"


def test_api_receipt_endpoint():
    # Arbitrary transaction without record must return 404
    resp = client.get("/api/v1/receipts/9912042")
    assert resp.status_code == 404

    # Real lifecycle: request, verify, redeem mandate to produce an actual transaction
    req = client.post(
        "/api/v1/mandates/request",
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
        json={"mode": "keypad", "stated_amount": 3000.0, "attempt": 1},
    )
    assert ver.status_code == 200
    code = ver.json()["one_time_code"]

    red = client.post(
        f"/api/v1/mandates/{mandate_id}/redeem",
        json={"code": code},
    )
    assert red.status_code == 200
    txn_id = red.json()["txn_id"]

    # Now receipt endpoint resolves the real runtime record
    rcpt_resp = client.get(f"/api/v1/receipts/{txn_id}")
    assert rcpt_resp.status_code == 200
    rcpt_data = rcpt_resp.json()
    assert rcpt_data["txn_id"] == txn_id
    assert rcpt_data["amount_bdt"] == 3000.0
    assert "৩,০০০" in rcpt_data["receipt_text_bn"]
    assert rcpt_data["provenance"] == "runtime memory, not a database record"
    assert "ts" in rcpt_data and rcpt_data["ts"] is not None


def test_api_metrics_summary():
    resp = client.get("/api/v1/metrics/summary")
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()
