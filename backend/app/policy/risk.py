"""Real-time mandate risk assessment (Track 01: Trust & Risk Intelligence).

The engine scores each cash-out mandate at request time from durable ledger signals and
the saved agent anomaly score. The score never approves or denies money movement. It only
chooses how strong the customer's independent verification must be:

- low    -> keypad_or_call   (app keypad or outbound call)
- medium -> call_required    (outbound call to the registered phone)
- high   -> call_and_review  (outbound call and an analyst review case)

Weights are documented ASSUMPTIONS on synthetic data, kept in this file next to the rule
trace so every point of score can be explained to an analyst.
"""

from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

ENGINE_VERSION = "mandate_risk_v1"
DHAKA = ZoneInfo("Asia/Dhaka")
INTERCEPT = -2.6

# ASSUMPTION weights (log-odds contribution when the signal fires at full strength).
WEIGHTS: dict[str, float] = {
    "agent_anomaly": 2.2,
    "agent_watchlisted": 3.0,
    "amount_vs_history": 1.1,
    "new_agent_customer_pair": 0.6,
    "agent_velocity": 1.0,
    "agent_recent_cases": 1.2,
    "customer_recent_mismatch": 1.3,
    "night_request": 0.5,
    "near_cap": 0.4,
    "rapid_full_withdrawal": 0.7,
}

BANDS = (("low", 0.30), ("medium", 0.60), ("high", 1.01))
STEP_UP = {"low": "keypad_or_call", "medium": "call_required", "high": "call_and_review"}


@dataclass
class RiskAssessment:
    mandate_id: str
    score: float
    band: str
    step_up: str
    reasons: list[dict[str, Any]] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "score": round(self.score, 4),
            "band": self.band,
            "step_up": self.step_up,
            "reasons": self.reasons,
            "engine_version": self.engine_version,
            "decision_boundary": "Risk sets verification strength only; it never authorizes "
            "or denies a cash-out.",
        }


def band_for(score: float) -> str:
    for name, upper in BANDS:
        if score < upper:
            return name
    return "high"


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_signals(signals: dict[str, dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    """Combine normalized signal strengths (0..1) into a calibrated-looking 0..1 score.

    Returns the score and a rule trace sorted by contribution.
    """
    z = INTERCEPT
    trace = []
    for name, weight in WEIGHTS.items():
        sig = signals.get(name)
        if not sig:
            continue
        strength = _clip(float(sig["strength"]))
        contribution = weight * strength
        z += contribution
        if strength > 0:
            trace.append(
                {
                    "signal": name,
                    "strength": round(strength, 3),
                    "contribution": round(contribution, 3),
                    "observed": sig.get("observed"),
                    "reference": sig.get("reference"),
                    "explanation": sig.get("explanation", ""),
                }
            )
    score = 1.0 / (1.0 + math.exp(-z))
    trace.sort(key=lambda item: -item["contribution"])
    return score, trace


class MandateRiskEngine:
    """Computes and persists mandate risk using one short read transaction."""

    def __init__(
        self,
        get_connection: Callable[[], Any],
        agent_score_lookup: Callable[[str], float | None] | None = None,
        cap: Decimal | float = 5000,
        now: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._get_connection = get_connection
        self._agent_score_lookup = agent_score_lookup
        self._cap = float(cap)
        self._now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def collect_signals(
        self, cur: Any, user_id: str, agent_id: str, amount: float, mandate_id: str
    ) -> dict[str, dict[str, Any]]:
        now = self._now()
        signals: dict[str, dict[str, Any]] = {}

        # Customer's own cash-out history (median of last 90 days).
        cur.execute(
            """
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount), count(*)
            FROM transactions
            WHERE user_id = %s AND txn_type = 'cash_out' AND ts > %s - interval '90 days';
            """,
            (user_id, now),
        )
        median, count = cur.fetchone()
        if count and median:
            ratio = amount / float(median)
            signals["amount_vs_history"] = {
                "strength": _clip((ratio - 1.5) / 2.0),
                "observed": round(ratio, 2),
                "reference": "1.5x the customer's 90-day median cash-out",
                "explanation": f"Requested amount is {ratio:.1f}x this customer's usual cash-out.",
            }
        else:
            signals["amount_vs_history"] = {
                "strength": 0.3,
                "observed": "no history",
                "reference": "at least one prior cash-out",
                "explanation": "No prior cash-out history for this customer.",
            }

        # First time this agent serves this customer.
        cur.execute(
            """
            SELECT count(*) FROM transactions
            WHERE user_id = %s AND agent_id = %s AND txn_type = 'cash_out';
            """,
            (user_id, agent_id),
        )
        prior_pair = cur.fetchone()[0]
        signals["new_agent_customer_pair"] = {
            "strength": 1.0 if prior_pair == 0 else 0.0,
            "observed": int(prior_pair),
            "reference": "prior cash-outs with this agent",
            "explanation": "First cash-out between this agent and customer."
            if prior_pair == 0 else "",
        }

        # Agent velocity: distinct customers requested in the last 30 minutes.
        cur.execute(
            """
            SELECT count(DISTINCT user_id) FROM mandates
            WHERE agent_id = %s AND created_at > %s - interval '30 minutes'
              AND mandate_id <> %s;
            """,
            (agent_id, now, mandate_id),
        )
        velocity = int(cur.fetchone()[0])
        signals["agent_velocity"] = {
            "strength": _clip((velocity - 2) / 4.0),
            "observed": velocity,
            "reference": "more than 2 other customers in 30 minutes",
            "explanation": f"Agent requested mandates for {velocity} other customers "
            "in the last 30 minutes." if velocity > 2 else "",
        }

        # Analyst-controlled enhanced-verification watchlist.
        cur.execute("SELECT reason FROM agent_watchlist WHERE agent_id = %s;", (agent_id,))
        watch = cur.fetchone()
        signals["agent_watchlisted"] = {
            "strength": 1.0 if watch else 0.0,
            "observed": bool(watch),
            "reference": "analyst watchlist",
            "explanation": f"Agent is on the analyst watchlist: {watch[0]}" if watch else "",
        }

        # Recent review cases against the agent (mismatch, cash gap, duress).
        cur.execute(
            """
            SELECT count(*) FROM cases
            WHERE agent_id = %s AND created_at > %s - interval '7 days';
            """,
            (agent_id, now),
        )
        agent_cases = int(cur.fetchone()[0])
        signals["agent_recent_cases"] = {
            "strength": _clip(agent_cases / 3.0),
            "observed": agent_cases,
            "reference": "review cases against agent in 7 days",
            "explanation": f"{agent_cases} review case(s) opened against this agent this week."
            if agent_cases else "",
        }

        # Customer's recent failed confirmations.
        cur.execute(
            """
            SELECT count(*) FROM verification_events v JOIN mandates m USING (mandate_id)
            WHERE m.user_id = %s AND v.outcome = 'mismatch' AND v.ts > %s - interval '24 hours';
            """,
            (user_id, now),
        )
        mismatches = int(cur.fetchone()[0])
        signals["customer_recent_mismatch"] = {
            "strength": _clip(mismatches / 2.0),
            "observed": mismatches,
            "reference": "amount mismatches in 24 hours",
            "explanation": f"Customer gave a different amount {mismatches} time(s) today."
            if mismatches else "",
        }

        # Rapid near-full withdrawal right after a credit (allowance pattern).
        cur.execute(
            """
            SELECT amount, ts FROM transactions
            WHERE user_id = %s AND txn_type = 'credit' AND ts <= %s
            ORDER BY ts DESC LIMIT 1;
            """,
            (user_id, now),
        )
        credit = cur.fetchone()
        if credit:
            credit_amount, credit_ts = float(credit[0]), credit[1]
            hours = (now - credit_ts).total_seconds() / 3600
            share = amount / credit_amount if credit_amount else 0.0
            fires = hours <= 24 and share >= 0.9
            signals["rapid_full_withdrawal"] = {
                "strength": 1.0 if fires else 0.0,
                "observed": {"hours_since_credit": round(hours, 1), "share": round(share, 2)},
                "reference": ">=90% of last credit within 24 hours",
                "explanation": "Nearly the full credit is withdrawn within a day of arrival."
                if fires else "",
            }

        local_hour = now.astimezone(DHAKA).hour
        night = local_hour >= 22 or local_hour < 6
        signals["night_request"] = {
            "strength": 1.0 if night else 0.0,
            "observed": local_hour,
            "reference": "22:00-06:00 Asia/Dhaka",
            "explanation": "Request made at night." if night else "",
        }

        near = amount >= 0.9 * self._cap
        signals["near_cap"] = {
            "strength": 1.0 if near else 0.0,
            "observed": amount,
            "reference": f"90% of the {self._cap:.0f} BDT mandate cap",
            "explanation": "Amount is close to the per-mandate cap." if near else "",
        }

        if self._agent_score_lookup is not None:
            try:
                agent_score = self._agent_score_lookup(agent_id)
            except Exception:
                agent_score = None
            if agent_score is not None:
                signals["agent_anomaly"] = {
                    "strength": _clip((agent_score - 0.5) / 0.4),
                    "observed": round(agent_score, 3),
                    "reference": "saved peer anomaly score above 0.5",
                    "explanation": f"Saved agent anomaly score {agent_score:.2f} "
                    "(review score, not fraud probability)." if agent_score > 0.5 else "",
                }
        return signals

    def assess(
        self, mandate_id: str, user_id: str, agent_id: str, amount: float, persist: bool = True
    ) -> RiskAssessment:
        conn = self._get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    signals = self.collect_signals(
                        cur, user_id, agent_id, float(amount), mandate_id
                    )
                    score, trace = score_signals(signals)
                    band = band_for(score)
                    if signals.get("agent_watchlisted", {}).get("strength") and band == "low":
                        band = "medium"  # watchlist always requires the call channel
                    result = RiskAssessment(mandate_id, score, band, STEP_UP[band], trace)
                    if persist:
                        cur.execute(
                            """
                            INSERT INTO mandate_risk (
                                mandate_id, score, band, step_up, reasons, engine_version
                            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                            ON CONFLICT (mandate_id) DO NOTHING;
                            """,
                            (mandate_id, round(score, 4), band, result.step_up,
                             json.dumps(trace), ENGINE_VERSION),
                        )
                        if band == "high":
                            cur.execute(
                                """
                                INSERT INTO cases (
                                    mandate_id, agent_id, reason, evidence, status, created_at
                                ) VALUES (%s, %s, 'high_risk_request', %s::jsonb, 'open', now());
                                """,
                                (mandate_id, agent_id, json.dumps(
                                    {"risk_score": round(score, 4), "amount": float(amount),
                                     "signals": trace})),
                            )
            return result
        finally:
            conn.close()

    @staticmethod
    def fail_safe(mandate_id: str) -> RiskAssessment:
        """When signals cannot be read, require the stronger channel instead of failing open."""
        return RiskAssessment(
            mandate_id, 0.5, "medium", STEP_UP["medium"],
            [{"signal": "risk_engine_unavailable", "strength": 1.0, "contribution": 0.0,
              "observed": None, "reference": None,
              "explanation": "Risk signals unavailable; stronger verification required."}],
        )

    def load(self, mandate_id: str) -> RiskAssessment | None:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT score, band, step_up, reasons, engine_version FROM mandate_risk "
                    "WHERE mandate_id = %s;",
                    (mandate_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        reasons = row[3] if isinstance(row[3], list) else json.loads(row[3])
        return RiskAssessment(mandate_id, float(row[0]), row[1], row[2], reasons, row[4])
