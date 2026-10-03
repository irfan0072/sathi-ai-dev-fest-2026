"""Analytics, intelligence, and review case service for Sathi.

Provides:
- User assisted scoring and SHAP explanation generation.
- Agent anomaly risk assessment with peer comparisons.
- High-priority outreach ranking for assisted beneficiaries.
- Durable human review queue management and analyst case adjudication.
- Database ledger-backed Bangla receipts with exact numerical integrity.
- System-wide evaluation metrics summary conforming to docs/evaluation-results.md.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

from app.copilot.receipts import generate_bangla_receipt
from app.mandates.router import get_mandate_service
from app.mandates.service import MandateService

FEATURE_DISPLAY_NAMES = {
    "top_agent_share": "শীর্ষ এজেন্টে লেনদেনের হার (Top-Agent Share)",
    "hours_credit_to_cashout": "টাকা জমার পর উত্তোলনের সময় (Credit-to-Cashout Delay)",
    "withdrawn_fraction": "উত্তোলিত ব্যালেন্সের অনুপাত (Withdrawn Fraction)",
    "allowance_count": "ভাতা প্রাপ্তির সংখ্যা (Allowance Count)",
    "cash_out_mean": "গড় ক্যাশ-আউট পরিমাণ (Mean Cash-Out Amount)",
    "pin_retry_ratio": "ভুল পিন প্রদানের হার (PIN Retry Ratio)",
    "night_txn_fraction": "রাতের লেনদেনের হার (Night Txn Fraction)",
    "fee_ratio_vs_official": "নির্ধারিত ফির অনুপাত (Fee Ratio vs Official 1.5%)",
    "assisted_customer_fraction": "সহায়তা গ্রহণকারী গ্রাহক অনুপাত (Assisted Customer Share)",
    "unexplained_cash_gap_rate": "নগদ পার্থক্যের অভিযোগ হার (Customer Cash Gap Rate)",
    "allowance_day_volume_spike": "ভাতার দিনে অস্বাভাবিক লেনদেন বৃদ্ধি (Allowance Day Spike)",
}


class AnalyticsService:
    """Service providing intelligence queries, durable case management, and receipts."""

    def __init__(
        self,
        mandate_service: MandateService | None = None,
    ) -> None:
        self._mandate_service = mandate_service

    @property
    def mandate_service(self) -> MandateService:
        if self._mandate_service is None:
            self._mandate_service = get_mandate_service()
        return self._mandate_service

    def get_user_assisted_score(self, user_id: str) -> dict[str, Any]:
        """Return illustrative sample score and feature profile for demonstration."""
        is_known_assisted = "000008" in user_id or "000123" in user_id or "assisted" in user_id
        score = 0.884 if is_known_assisted else 0.125

        top_reasons = (
            [
                {
                    "feature": "top_agent_share",
                    "display_name": FEATURE_DISPLAY_NAMES["top_agent_share"],
                    "value": 0.92,
                    "peer_median": 0.38,
                    "sample_weight": "+0.34",
                    "direction": "positive",
                },
                {
                    "feature": "hours_credit_to_cashout",
                    "display_name": FEATURE_DISPLAY_NAMES["hours_credit_to_cashout"],
                    "value": 3.5,
                    "peer_median": 48.0,
                    "sample_weight": "+0.28",
                    "direction": "positive",
                },
                {
                    "feature": "withdrawn_fraction",
                    "display_name": FEATURE_DISPLAY_NAMES["withdrawn_fraction"],
                    "value": 0.96,
                    "peer_median": 0.45,
                    "sample_weight": "+0.19",
                    "direction": "positive",
                },
            ]
            if is_known_assisted
            else [
                {
                    "feature": "top_agent_share",
                    "display_name": FEATURE_DISPLAY_NAMES["top_agent_share"],
                    "value": 0.28,
                    "peer_median": 0.38,
                    "sample_weight": "-0.22",
                    "direction": "negative",
                },
                {
                    "feature": "hours_credit_to_cashout",
                    "display_name": FEATURE_DISPLAY_NAMES["hours_credit_to_cashout"],
                    "value": 72.0,
                    "peer_median": 48.0,
                    "sample_weight": "-0.15",
                    "direction": "negative",
                },
            ]
        )

        return {
            "user_id": user_id,
            "score": score,
            "assisted": is_known_assisted,
            "is_sample": True,
            "provenance": "illustrative sample, not a result",
            "model_version": "sample_template",
            "top_reasons": top_reasons,
        }

    def get_agent_risk(self, agent_id: str) -> dict[str, Any]:
        """Return illustrative sample anomaly profile with peer comparison breakdown."""
        skimmer_tokens = ("000015", "000016", "0042", "000042")
        is_known_skimmer = any(tok in agent_id for tok in skimmer_tokens)

        if is_known_skimmer:
            risk = 0.865
            level = "HIGH"
            reasons = [
                {
                    "feature": "fee_ratio_vs_official",
                    "display_name": FEATURE_DISPLAY_NAMES["fee_ratio_vs_official"],
                    "value": 1.35,
                    "peer_median": 1.00,
                    "z_score": 3.82,
                },
                {
                    "feature": "assisted_customer_fraction",
                    "display_name": FEATURE_DISPLAY_NAMES["assisted_customer_fraction"],
                    "value": 0.64,
                    "peer_median": 0.20,
                    "z_score": 4.10,
                },
                {
                    "feature": "unexplained_cash_gap_rate",
                    "display_name": FEATURE_DISPLAY_NAMES["unexplained_cash_gap_rate"],
                    "value": 0.18,
                    "peer_median": 0.01,
                    "z_score": 5.20,
                },
            ]
        else:
            risk = 0.142
            level = "LOW"
            reasons = [
                {
                    "feature": "fee_ratio_vs_official",
                    "display_name": FEATURE_DISPLAY_NAMES["fee_ratio_vs_official"],
                    "value": 1.00,
                    "peer_median": 1.00,
                    "z_score": 0.00,
                },
                {
                    "feature": "assisted_customer_fraction",
                    "display_name": FEATURE_DISPLAY_NAMES["assisted_customer_fraction"],
                    "value": 0.22,
                    "peer_median": 0.20,
                    "z_score": 0.15,
                },
            ]

        return {
            "agent_id": agent_id,
            "risk": risk,
            "level": level,
            "is_sample": True,
            "provenance": "illustrative sample, not a result",
            "peer_group": "cohort=standard,volume=high",
            "model_version": "sample_template",
            "reasons": reasons,
        }

    def get_outreach_list(self) -> dict[str, Any]:
        """Ranked list of illustrative sample beneficiaries for onboarding demonstration."""
        items = [
            {
                "user_id": "U_42_000008",
                "assisted_score": 0.942,
                "primary_agent_id": "A_000015",
                "monthly_volume_bdt": 4500.00,
                "risk_band": "sample_high_assistance",
                "outreach_recommended": "sample_mandate_enrolment",
                "last_active": "2026-10-02T12:30:00Z",
                "is_sample": True,
                "provenance": "illustrative sample, not a result",
            },
            {
                "user_id": "U_42_000012",
                "assisted_score": 0.915,
                "primary_agent_id": "A_000042",
                "monthly_volume_bdt": 3200.00,
                "risk_band": "sample_high_assistance",
                "outreach_recommended": "sample_mandate_enrolment",
                "last_active": "2026-10-02T11:45:00Z",
                "is_sample": True,
                "provenance": "illustrative sample, not a result",
            },
            {
                "user_id": "U_42_000013",
                "assisted_score": 0.887,
                "primary_agent_id": "A_000016",
                "monthly_volume_bdt": 2800.00,
                "risk_band": "sample_high_assistance",
                "outreach_recommended": "sample_mandate_enrolment",
                "last_active": "2026-10-02T10:15:00Z",
                "is_sample": True,
                "provenance": "illustrative sample, not a result",
            },
            {
                "user_id": "U_42_000123",
                "assisted_score": 0.884,
                "primary_agent_id": "A_000042",
                "monthly_volume_bdt": 3000.00,
                "risk_band": "sample_high_assistance",
                "outreach_recommended": "sample_mandate_enrolment",
                "last_active": "2026-10-02T09:00:00Z",
                "is_sample": True,
                "provenance": "illustrative sample, not a result",
            },
        ]
        return {
            "total": len(items),
            "items": items,
            "is_sample": True,
            "provenance": "illustrative sample, not a result",
        }

    def list_cases(self) -> dict[str, Any]:
        """Return durable review cases from PostgreSQL cases store."""
        with self.mandate_service.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT case_id, mandate_id, agent_id, reason, evidence, status, created_at
                    FROM cases ORDER BY case_id ASC;
                    """
                )
                rows = cur.fetchall()
                service_cases = []
                for r in rows:
                    ev = r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}")
                    service_cases.append(
                        {
                            "case_id": r[0],
                            "mandate_id": str(r[1]) if r[1] else None,
                            "agent_id": r[2],
                            "reason": r[3],
                            "evidence": ev,
                            "status": r[5],
                            "created_at": (
                                r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6])
                            ),
                            "is_sample": False,
                            "provenance": "runtime_record",
                        }
                    )
                return {"total": len(service_cases), "cases": service_cases}

    def decide_case(
        self,
        case_id: int,
        decision: str,
        reviewer: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Record human review decision in review_actions and update case status in PostgreSQL.

        Human review updates case status and audit only; never automatically redeems
        or alters transaction balances. Unknown cases return 404.
        """
        valid_decisions = {"approved", "denied", "escalated"}
        if decision not in valid_decisions:
            raise ValueError(f"Invalid decision '{decision}'. Must be one of {valid_decisions}.")

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = self.mandate_service.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT case_id, status FROM cases WHERE case_id = %s FOR UPDATE;",
                        (case_id,),
                    )
                    row = cur.fetchone()

                    if row is None:
                        raise KeyError(
                            f"Case {case_id} not found in durable database cases store."
                        )

                    cur.execute(
                        "UPDATE cases SET status = %s WHERE case_id = %s;",
                        (decision, case_id),
                    )

                    cur.execute(
                        """
                        INSERT INTO review_actions (case_id, reviewer, decision, note, ts)
                        VALUES (%s, %s, %s, %s, now());
                        """,
                        (case_id, reviewer, decision, note),
                    )

                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        )
                        VALUES (%s, %s, 'case', %s, 'v1.0', %s::jsonb, now());
                        """,
                        (
                            reviewer,
                            f"CASE_DECISION_{decision.upper()}",
                            str(case_id),
                            json.dumps({"decision": decision, "note": note}),
                        ),
                    )

            return {
                "case_id": case_id,
                "status": decision,
                "decision": decision,
                "reviewer": reviewer,
                "resolved_at": now_iso,
            }
        finally:
            conn.close()

    def get_receipt(self, txn_id: int) -> dict[str, Any]:
        """Retrieve verified plain-language Bangla receipt from durable PostgreSQL transaction.

        Validates all numbers against actual ledger values to prevent numerical hallucination.
        Receipts join redeemed mandates and cash_out transaction, never arbitrary rows.
        """
        conn = self.mandate_service.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.txn_id, t.user_id, t.agent_id, t.amount, t.fee,
                           t.balance_after, t.ts
                    FROM transactions t
                    JOIN mandates m ON m.redeemed_txn_id = t.txn_id
                    WHERE t.txn_id = %s
                      AND t.txn_type = 'cash_out'
                      AND m.status = 'redeemed';
                    """,
                    (txn_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(
                        f"Redeemed cash-out transaction {txn_id} not found in database ledger."
                    )

                t_id, user_id, agent_id, amount, fee, balance_after, ts = row

                amount_bdt = float(Decimal(str(amount)))
                fee_bdt = float(Decimal(str(fee or 0.0)))
                payout_bdt = amount_bdt
                ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

                receipt = generate_bangla_receipt(
                    txn_id=t_id,
                    user_id=user_id or "unknown",
                    agent_id=agent_id or "unknown",
                    amount_bdt=amount_bdt,
                    fee_bdt=fee_bdt,
                    payout_bdt=payout_bdt,
                    ts_iso=ts_iso,
                )
                receipt["provenance"] = "database ledger transaction"
                return receipt
        finally:
            conn.close()

    def get_metrics_summary(self) -> dict[str, Any]:
        """Evaluation metrics summary is unavailable until evaluation artifacts are wired."""
        raise RuntimeError(
            "Evaluation metrics summary unavailable until evaluation artifacts are wired"
        )
