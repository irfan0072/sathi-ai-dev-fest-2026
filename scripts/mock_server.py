#!/usr/bin/env python3
"""Interactive mock server for Sathi Console development.

Provides realistic mock endpoints conforming to docs/console-mock-contract.md.
Interactive API documentation available at http://127.0.0.1:<port>/docs.
"""

import argparse
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

mock_app = FastAPI(
    title="Sathi Mock API",
    version="1.0.0",
    description="Mock backend server for frontend console development against Sathi API contracts.",
)

mock_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory mock database
MOCK_MANDATES: dict[str, dict[str, Any]] = {}
MOCK_CASES: list[dict[str, Any]] = [
    {
        "case_id": 1042,
        "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
        "user_id": "U_42_000123",
        "agent_id": "A_000042",
        "reason": "Amount mismatch: requested 3000 BDT, customer stated 2500 BDT",
        "status": "open",
        "severity": "HIGH",
        "created_at": "2026-10-02T18:31:00Z",
        "evidence": {
            "requested_amount": 3000.00,
            "stated_amount": 2500.00,
            "agent_risk_score": 0.865,
            "user_assisted_score": 0.884,
            "previous_cases_count": 0,
        },
    }
]


class MandateRequest(BaseModel):
    user_id: str
    agent_id: str
    amount: float
    purpose: str = "cash_out"


class VerifyRequest(BaseModel):
    mode: str = "keypad"
    stated_amount: float
    attempt: int = 1


class RedeemRequest(BaseModel):
    code: str


class ConfirmCashRequest(BaseModel):
    cash_received: float


class RevokeRequest(BaseModel):
    reason: str


class CaseDecisionRequest(BaseModel):
    decision: str
    reviewer: str
    note: str = ""


@mock_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "mock"}


@mock_app.post("/api/v1/mandates/request", status_code=201)
def request_mandate(req: MandateRequest) -> dict[str, Any]:
    mid = str(uuid.uuid4())
    record = {
        "mandate_id": mid,
        "user_id": req.user_id,
        "agent_id": req.agent_id,
        "amount": req.amount,
        "purpose": req.purpose,
        "status": "requested",
        "one_time_code": "849201",
    }
    MOCK_MANDATES[mid] = record
    return {
        "mandate_id": mid,
        "user_id": req.user_id,
        "agent_id": req.agent_id,
        "amount": req.amount,
        "status": "requested",
        "next": "verify",
        "verification_modes": ["keypad", "voice"],
        "created_at": "2026-10-02T18:30:00Z",
    }


@mock_app.post("/api/v1/mandates/{mandate_id}/verify")
def verify_mandate(mandate_id: str, req: VerifyRequest) -> dict[str, Any]:
    mandate = MOCK_MANDATES.get(mandate_id)
    req_amt = mandate["amount"] if mandate else 3000.00

    if abs(req.stated_amount - req_amt) > 0.01:
        case_id = 1000 + len(MOCK_CASES) + 1
        case = {
            "case_id": case_id,
            "mandate_id": mandate_id,
            "user_id": mandate["user_id"] if mandate else "U_42_000123",
            "agent_id": mandate["agent_id"] if mandate else "A_000042",
            "reason": (
                f"Amount mismatch: requested {req_amt:.0f} BDT, customer entered "
                f"{req.stated_amount:.0f} BDT"
            ),
            "status": "open",
            "severity": "HIGH",
            "created_at": "2026-10-02T18:31:00Z",
            "evidence": {
                "requested_amount": req_amt,
                "stated_amount": req.stated_amount,
                "agent_risk_score": 0.865,
                "user_assisted_score": 0.884,
            },
        }
        MOCK_CASES.append(case)
        return {
            "mandate_id": mandate_id,
            "outcome": "mismatch",
            "decision": "REVIEW",
            "status": "requested",
            "case_id": case_id,
            "reason": case["reason"],
            "customer_prompt_bn": "আপনার টাকার পরিমাণে অমিল পাওয়া গেছে। পর্যালোচনার জন্য পাঠানো হয়েছে।",
        }

    if mandate:
        mandate["status"] = "active"

    return {
        "mandate_id": mandate_id,
        "outcome": "match",
        "decision": "ISSUE_MANDATE",
        "status": "active",
        "expires_at": "2026-10-02T18:45:00Z",
        "code_delivery": "agent_terminal",
        "one_time_code": mandate["one_time_code"] if mandate else "849201",
        "customer_prompt_bn": "আপনার ৩,০০০ টাকা ক্যাশ-আউট অনুমোদিত হয়েছে। এজেন্টকে কোডটি বলুন।",
    }


@mock_app.post("/api/v1/mandates/{mandate_id}/redeem")
def redeem_mandate(mandate_id: str, req: RedeemRequest) -> dict[str, Any]:
    mandate = MOCK_MANDATES.get(mandate_id)
    expected_code = mandate["one_time_code"] if mandate else "849201"
    if req.code != expected_code:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {"code": "INVALID_CODE", "message": "Incorrect one-time code."}
            },
        )

    if mandate:
        mandate["status"] = "redeemed"

    amt = mandate["amount"] if mandate else 3000.00
    fee = round(amt * 0.015, 2)
    return {
        "mandate_id": mandate_id,
        "txn_id": 9912042,
        "amount": amt,
        "fee": fee,
        "status": "redeemed",
        "redeemed_at": "2026-10-02T18:32:15Z",
    }


@mock_app.post("/api/v1/mandates/{mandate_id}/confirm-cash")
def confirm_cash(mandate_id: str, req: ConfirmCashRequest) -> dict[str, Any]:
    expected = 2955.00
    gap = round(abs(expected - req.cash_received), 2)
    flagged = gap > 60.00
    return {
        "mandate_id": mandate_id,
        "cash_received": req.cash_received,
        "expected_payout": expected,
        "gap": gap,
        "flagged": flagged,
        "tolerance_bdt": 60.00,
        "note": "Reported cash gap exceeds tolerance." if flagged else "Cash verified.",
    }


@mock_app.post("/api/v1/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str, req: RevokeRequest) -> dict[str, Any]:
    if mandate_id in MOCK_MANDATES:
        MOCK_MANDATES[mandate_id]["status"] = "revoked"
    return {
        "mandate_id": mandate_id,
        "status": "revoked",
        "revoked_at": "2026-10-02T18:33:00Z",
    }


@mock_app.get("/api/v1/users/{user_id}/assisted-score")
def user_assisted_score(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "score": 0.884,
        "assisted": True,
        "confidence": 0.912,
        "model_version": "lgbm_assisted_v1",
        "top_reasons": [
            {
                "feature": "top_agent_share",
                "display_name": "শীর্ষ এজেন্টে লেনদেনের হার (Top-Agent Share)",
                "value": 0.92,
                "peer_median": 0.38,
                "shap_impact": "+0.34",
                "direction": "positive",
            },
            {
                "feature": "hours_credit_to_cashout",
                "display_name": "টাকা জমার পর উত্তোলনের সময় (Hours Credit-to-Cashout)",
                "value": 3.5,
                "peer_median": 48.0,
                "shap_impact": "+0.28",
                "direction": "positive",
            },
            {
                "feature": "withdrawn_fraction",
                "display_name": "উত্তোলিত ব্যালেন্সের অনুপাত (Withdrawn Fraction)",
                "value": 0.96,
                "peer_median": 0.45,
                "shap_impact": "+0.19",
                "direction": "positive",
            },
        ],
    }


@mock_app.get("/api/v1/agents/{agent_id}/risk")
def agent_risk(agent_id: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "risk": 0.865,
        "level": "HIGH",
        "peer_group": "region=rajshahi,volume=high",
        "model_version": "isolation_forest_peer_z_v1",
        "reasons": [
            {
                "feature": "fee_ratio_vs_official",
                "display_name": "ফি অনুপাত (Fee Ratio vs Official 1.5%)",
                "value": 1.35,
                "peer_median": 1.00,
                "z_score": 3.82,
            },
            {
                "feature": "assisted_customer_fraction",
                "display_name": "সহায়তা গ্রহণকারী গ্রাহক অনুপাত (Assisted Share)",
                "value": 0.64,
                "peer_median": 0.20,
                "z_score": 4.10,
            },
            {
                "feature": "unexplained_cash_gap_rate",
                "display_name": "গ্রাহকের নগদ পার্থক্যের হার (Customer Cash Gap)",
                "value": 0.18,
                "peer_median": 0.01,
                "z_score": 5.20,
            },
        ],
    }


@mock_app.get("/api/v1/outreach")
def outreach_list() -> dict[str, Any]:
    return {
        "total": 2,
        "items": [
            {
                "user_id": "U_42_000123",
                "assisted_score": 0.942,
                "primary_agent_id": "A_000042",
                "monthly_volume_bdt": 4500.00,
                "risk_band": "high_assistance",
                "outreach_recommended": "assisted_mandate_enrolment",
                "last_active": "2026-10-02T12:30:00Z",
            },
            {
                "user_id": "U_42_000512",
                "assisted_score": 0.895,
                "primary_agent_id": "A_000015",
                "monthly_volume_bdt": 3000.00,
                "risk_band": "high_assistance",
                "outreach_recommended": "assisted_mandate_enrolment",
                "last_active": "2026-10-02T10:15:00Z",
            },
        ],
    }


@mock_app.get("/api/v1/cases")
def list_cases() -> dict[str, Any]:
    return {"total": len(MOCK_CASES), "cases": MOCK_CASES}


@mock_app.post("/api/v1/cases/{case_id}/decision")
def decide_case(case_id: int, req: CaseDecisionRequest) -> dict[str, Any]:
    for c in MOCK_CASES:
        if c["case_id"] == case_id:
            c["status"] = req.decision
            c["reviewer"] = req.reviewer
            c["note"] = req.note
            return {
                "case_id": case_id,
                "status": req.decision,
                "decision": req.decision,
                "reviewer": req.reviewer,
                "resolved_at": "2026-10-02T18:35:10Z",
            }
    raise HTTPException(status_code=404, detail="Case not found")


@mock_app.get("/api/v1/receipts/{txn_id}")
def get_receipt(txn_id: int) -> dict[str, Any]:
    return {
        "txn_id": txn_id,
        "user_id": "U_42_000123",
        "agent_id": "A_000042",
        "amount_bdt": 3000.00,
        "fee_bdt": 45.00,
        "payout_bdt": 2955.00,
        "ts": "2026-10-02T18:32:15Z",
        "receipt_text_bn": (
            f"সাথী ক্যাশ-আউট সফল হয়েছে। উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫ টাকা (১.৫%), "
            f"প্রাপ্ত অর্থ: ২,৯৫৫ টাকা। এজেন্ট: A_000042, ট্রানজ্যাকশন আইডি: {txn_id}।"
        ),
    }


@mock_app.get("/api/v1/metrics/summary")
def get_metrics_summary() -> dict[str, Any]:
    return {
        "evaluation_dataset": "synthetic_seed_4242",
        "assisted_classifier": {
            "model": "LightGBM",
            "pr_auc": 0.942,
            "roc_auc": 0.961,
            "f1_score": 0.891,
            "baseline_rule_pr_auc": 0.785,
            "lift_over_baseline": "+19.9%",
        },
        "agent_anomaly": {
            "model": "Isolation Forest + Robust Peer Z-Score",
            "precision_at_k": 0.85,
            "recall_skimmers": 0.90,
            "false_flag_rate_honest_high_volume": 0.05,
            "baseline_rule_precision": 0.62,
        },
        "fairness_slices": {
            "max_tpr_gap": 0.065,
            "target_tpr_gap": 0.10,
            "compliant": True,
            "by_gender": {
                "female": {"tpr": 0.892, "fpr": 0.041},
                "male": {"tpr": 0.915, "fpr": 0.038},
            },
            "by_urban_rural": {
                "urban": {"tpr": 0.908, "fpr": 0.039},
                "rural": {"tpr": 0.885, "fpr": 0.044},
            },
        },
        "impact_simulation": {
            "adoption_scenarios": [
                {
                    "adoption_rate": "30%",
                    "pin_disclosure_reduction": "30.0%",
                    "simulated_loss_prevented_bdt": 185000.00,
                },
                {
                    "adoption_rate": "50%",
                    "pin_disclosure_reduction": "50.0%",
                    "simulated_loss_prevented_bdt": 312000.00,
                },
                {
                    "adoption_rate": "70%",
                    "pin_disclosure_reduction": "70.0%",
                    "simulated_loss_prevented_bdt": 435000.00,
                },
            ]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Sathi mock server")
    parser.add_argument(
        "--port", type=int, default=18001, help="Port to bind (default: 18001)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    args = parser.parse_args()

    print(f"Starting Sathi Mock Server on http://{args.host}:{args.port}")
    print(f"Interactive Swagger Docs: http://{args.host}:{args.port}/docs")
    uvicorn.run(mock_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
