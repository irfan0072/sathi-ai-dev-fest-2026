"""Reproducible, configurable cost and break-even model for post-cash-out confirmation.

Every number is an ASSUMPTION unless it is labelled as coming from the local synthetic
workflow. There are no invoices and no field data. The model separates three things that the
first report mixed together:

1. Cost of running the confirmation workflow: placed call attempts (including failed ones),
   SMS, manual reviews, hosting. Answered and completed calls have their own denominators.
2. Detection: the call path can surface a customer-reported mismatch. Detection is not a
   saved taka. A flagged cash gap or a closed case is never counted as prevented or recovered.
3. Benefit: only what a SEPARATE, supported intervention (a hold, a reversal, a restitution)
   returns, modelled by an explicit `intervention_success_rate`. The primary cash-out has
   already completed when the call is made. With no intervention (rate 0) the net is
   the negative of the cost: that is the honest detection-only floor.

`reproduce_report_scenarios()` re-derives the first report's scenarios A, B and C (the
"prevention 50%" assumption) so the difference to the corrected view is visible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Assumptions:
    # Delivery
    call_coverage: float = 1.0            # share of cash-outs that are called
    answer_rate_per_attempt: float = 0.60  # P(one attempt answered); report gate: >= 60%
    max_attempts: int = 3                  # automatic attempts before a person takes over
    unanswered_billing_fraction: float = 1.0  # share of a call's price billed when unanswered
    # Unit costs (BDT)
    cost_per_call_attempt: float = 0.80    # local IVR, about 45 seconds (report assumption)
    sms_receipt: float = 0.30
    sms_missed_call: float = 0.25
    hosting_per_check: float = 0.10
    manual_minutes: float = 8.0
    manual_cost_per_hour: float = 250.0
    # Manual handling
    unclear_manual_share: float = 0.03     # answered but not understood twice (report assumption)
    # As implemented, a check that is unanswered after every attempt is marked "ignored";
    # a super admin may escalate it. Set 1.0 to cost a supervisor call for every one of them.
    unreachable_manual_share: float = 0.0
    # Suspicious cases need a human review and an independent follow-up contact.
    false_suspicious_rate: float = 0.02    # honest, answered checks that become cases (gate <=2%)
    case_minutes: float = 15.0             # case review plus independent follow-up, per case
    # Incidence and loss (synthetic simulator values)
    incident_rate: float = 244 / 8810      # skimmer actions per assisted cash-out (simulated)
    loss_per_incident: float = 61.0        # simulated average; the report quotes 150-300 as ranges
    # Detection and benefit
    detection_given_answered: float = 1.0  # share of incidents on answered calls that are flagged
    intervention_success_rate: float = 0.0  # only a separate supported intervention counts
    dispute_complaint_rate: float = 0.40   # incidents that become complaints (report assumption)
    dispute_cost: float = 150.0            # handling cost per complaint avoided
    count_dispute_savings: bool = False    # off by default: needs a resolved, confirmed case


def attempt_statistics(a: Assumptions) -> dict[str, float]:
    """Expected attempts and outcomes per CALLED cash-out under independent attempts."""
    miss = 1.0 - a.answer_rate_per_attempt
    expected_attempts = sum(miss ** i for i in range(a.max_attempts))
    answered = 1.0 - miss ** a.max_attempts
    return {"expected_attempts": expected_attempts, "answered_within_budget": answered,
            "unanswered_after_budget": 1.0 - answered,
            "failed_attempts": expected_attempts - answered}


def cost_per_1000(a: Assumptions) -> dict[str, float]:
    stats = attempt_statistics(a)
    called = 1000 * a.call_coverage
    manual_unit = a.manual_minutes / 60.0 * a.manual_cost_per_hour
    answered_calls = called * stats["answered_within_budget"]
    unanswered = called * stats["unanswered_after_budget"]
    detected = 1000 * a.incident_rate * a.call_coverage * stats["answered_within_budget"] \
        * a.detection_given_answered
    cases = answered_calls * a.false_suspicious_rate + detected
    billed_attempts = (answered_calls + called * stats["failed_attempts"]
                       * a.unanswered_billing_fraction)
    lines = {
        "call_attempts": billed_attempts * a.cost_per_call_attempt,
        "sms": called * a.sms_receipt + unanswered * a.sms_missed_call,
        "manual_review_unclear": answered_calls * a.unclear_manual_share * manual_unit,
        "manual_review_unreachable": unanswered * a.unreachable_manual_share * manual_unit,
        "case_review_and_independent_followup": cases * a.case_minutes / 60.0
        * a.manual_cost_per_hour,
        "hosting": called * a.hosting_per_check,
    }
    return {**{k: round(v, 2) for k, v in lines.items()}, "total": round(sum(lines.values()), 2)}


def benefit_per_1000(a: Assumptions) -> dict[str, float]:
    stats = attempt_statistics(a)
    incidents = 1000 * a.incident_rate
    reached = incidents * a.call_coverage * stats["answered_within_budget"]
    detected = reached * a.detection_given_answered
    recovered = detected * a.intervention_success_rate
    loss = recovered * a.loss_per_incident
    disputes = (recovered * a.dispute_complaint_rate * a.dispute_cost
                if a.count_dispute_savings else 0.0)
    return {"incidents": round(incidents, 2), "incidents_reached_by_call": round(reached, 2),
            "incidents_detected": round(detected, 2),
            "loss_returned_by_a_separate_intervention": round(loss, 2),
            "dispute_handling_avoided": round(disputes, 2),
            "total": round(loss + disputes, 2)}


def net_per_1000(a: Assumptions) -> dict[str, Any]:
    cost, benefit = cost_per_1000(a), benefit_per_1000(a)
    return {"cost": cost, "benefit": benefit, "net": round(benefit["total"] - cost["total"], 2),
            "delivery": {k: round(v, 4) for k, v in attempt_statistics(a).items()}}


def break_even_loss_per_incident(a: Assumptions) -> float | None:
    """Average loss per incident at which net = 0 for the given intervention success rate."""
    probe = replace(a, loss_per_incident=1.0)
    per_taka = benefit_per_1000(probe)["loss_returned_by_a_separate_intervention"]
    fixed = benefit_per_1000(a)["dispute_handling_avoided"]
    if per_taka <= 0:
        return None
    return round(max(0.0, (cost_per_1000(a)["total"] - fixed) / per_taka), 2)


def break_even_intervention_success(a: Assumptions) -> float | None:
    """Share of detected incidents a separate intervention must return for net = 0.
    None means no share up to 100% pays for the workflow (or no benefit is possible)."""
    probe = replace(a, intervention_success_rate=1.0)
    full = benefit_per_1000(probe)["total"]
    if full <= 0:
        return None
    needed = cost_per_1000(a)["total"] / full
    # A share above 100% means no intervention can pay for the workflow at this loss size.
    return round(needed, 4) if needed <= 1.0 else None


# --------------------------------------------------------------------------- report scenarios
def reproduce_report_scenarios() -> dict[str, Any]:
    """First report, per 1,000 assisted cash-outs: cost 2,200 / 2,200 / 880, 50% prevention,
    40% of incidents become 150-taka complaints. Re-derived with the same arithmetic."""
    incidents = 28.0  # the report rounds 1,000 x 244 / 8,810 = 27.7 to 28 incidents
    cost_all, cost_targeted = 2200.0, 880.0
    out = {}
    for name, cost, share_detected, loss in (("A", cost_all, 1.0, 61.0),
                                            ("B", cost_all, 1.0, 150.0),
                                            ("C", cost_targeted, 0.8, 61.0)):
        prevented = incidents * share_detected * 0.5
        benefit = prevented * (loss + 0.4 * 150.0)
        out[name] = {"cost": cost, "benefit": round(benefit), "net": round(benefit - cost),
                     "assumes": "every called incident is detected, 50% are PREVENTED, and "
                                "40% of those would have become 150-taka complaints"}
    return out


def corrected_view_of_report_scenarios() -> dict[str, Any]:
    """The same three scenarios with the delivery model and an explicit intervention rate.

    Detection-only (rate 0) is the floor; 0.5 is the report's prevention assumption, which
    needs a hold or reversal that the post-cash-out call does not provide by itself.
    """
    base = Assumptions()
    scenarios = {
        "A_all_calls_loss_61": replace(base, loss_per_incident=61.0),
        "B_all_calls_loss_150": replace(base, loss_per_incident=150.0),
        "C_targeted_40pct_loss_61": replace(base, call_coverage=0.4, loss_per_incident=61.0,
                                            detection_given_answered=0.8),
    }
    out = {}
    for name, assumption in scenarios.items():
        out[name] = {}
        for rate in (0.0, 0.1, 0.25, 0.5):
            for dispute in (False, True):
                a = replace(assumption, intervention_success_rate=rate,
                            count_dispute_savings=dispute)
                key = f"intervention_{int(rate * 100)}pct" + ("_with_dispute_savings"
                                                              if dispute else "")
                out[name][key] = net_per_1000(a)["net"]
        out[name]["cost_per_1000"] = cost_per_1000(scenarios[name])["total"]
        out[name]["break_even_intervention_success_no_dispute_savings"] = \
            break_even_intervention_success(scenarios[name])
        out[name]["break_even_loss_per_incident_at_50pct_intervention"] = \
            break_even_loss_per_incident(replace(scenarios[name], intervention_success_rate=0.5))
    return out


def sensitivity_grid(base: Assumptions | None = None) -> list[dict[str, Any]]:
    """Net per 1,000 cash-outs across answer rate, intervention success and loss."""
    base = base or Assumptions()
    rows = []
    for answer in (0.4, 0.6, 0.8):
        for rate in (0.0, 0.1, 0.25, 0.5):
            for loss in (61.0, 150.0, 300.0):
                a = replace(base, answer_rate_per_attempt=answer, intervention_success_rate=rate,
                            loss_per_incident=loss)
                result = net_per_1000(a)
                rows.append({"answer_rate_per_attempt": answer,
                             "intervention_success_rate": rate, "loss_per_incident": loss,
                             "cost": result["cost"]["total"], "benefit": result["benefit"]["total"],
                             "net": result["net"]})
    return rows


def full_report(base: Assumptions | None = None) -> dict[str, Any]:
    base = base or Assumptions()
    return {
        "status": "ASSUMPTIONS ONLY. No invoices, no field data, no measured loss prevention.",
        "assumptions": asdict(base),
        "baseline": net_per_1000(base),
        "break_even_loss_per_incident_at_intervention_rate": {
            f"{int(r * 100)}pct": break_even_loss_per_incident(
                replace(base, intervention_success_rate=r)) for r in (0.1, 0.25, 0.5)},
        "break_even_intervention_success": break_even_intervention_success(base),
        "first_report_scenarios_reproduced": reproduce_report_scenarios(),
        "same_scenarios_corrected_delivery_and_explicit_intervention":
            corrected_view_of_report_scenarios(),
        "sensitivity": sensitivity_grid(base),
        "not_counted": ["flagged cash gaps", "closed cases", "supervisor-confirmed findings "
                        "without restitution", "deterrence", "customer trust",
                        "regulatory value"],
    }
