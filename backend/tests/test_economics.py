"""Economics model: the first report's scenarios are reproduced exactly, and the corrected view
never turns detection into saved money."""

from __future__ import annotations

from dataclasses import replace

import pytest
from app.ops import economics as eco


def test_first_report_scenarios_are_reproduced_exactly():
    scenarios = eco.reproduce_report_scenarios()
    a = scenarios["A"]
    assert (a["cost"], a["benefit"], a["net"]) == (2200, 1694, -506)
    assert (scenarios["B"]["benefit"], scenarios["B"]["net"]) == (2940, 740)
    c = scenarios["C"]
    assert (c["cost"], c["benefit"], c["net"]) == (880, 1355, 475)


def test_detection_only_net_is_exactly_minus_cost():
    base = eco.Assumptions()
    result = eco.net_per_1000(base)
    assert result["benefit"]["total"] == 0 and result["net"] == -result["cost"]["total"]
    assert result["benefit"]["incidents_detected"] > 0         # detection is real, savings are not


def test_no_intervention_means_no_loss_is_counted_whatever_the_loss_size():
    for loss in (61, 150, 300, 5000):
        a = replace(eco.Assumptions(), loss_per_incident=loss, count_dispute_savings=True)
        assert eco.benefit_per_1000(a)["total"] == 0


def test_delivery_model_counts_failed_attempts_and_unanswered_checks():
    a = eco.Assumptions(answer_rate_per_attempt=0.6, max_attempts=3)
    stats = eco.attempt_statistics(a)
    assert stats["expected_attempts"] == pytest.approx(1 + 0.4 + 0.16)
    assert stats["answered_within_budget"] == pytest.approx(1 - 0.4 ** 3)
    assert stats["failed_attempts"] == pytest.approx(
        stats["expected_attempts"] - stats["answered_within_budget"])
    lower = eco.cost_per_1000(replace(a, answer_rate_per_attempt=0.4))["total"]
    higher = eco.cost_per_1000(replace(a, answer_rate_per_attempt=0.8))["total"]
    assert lower != higher


def test_cost_is_configurable_and_monotonic():
    base = eco.cost_per_1000(eco.Assumptions())["total"]
    assert eco.cost_per_1000(replace(eco.Assumptions(), cost_per_call_attempt=2.0))["total"] > base
    assert eco.cost_per_1000(replace(eco.Assumptions(), manual_cost_per_hour=500))["total"] > base
    assert eco.cost_per_1000(replace(eco.Assumptions(), call_coverage=0.4))["total"] < base
    manual = replace(eco.Assumptions(), unreachable_manual_share=1.0)
    assert eco.cost_per_1000(manual)["total"] > base


def test_break_even_values_are_consistent_with_net():
    a = replace(eco.Assumptions(), intervention_success_rate=0.5)
    loss = eco.break_even_loss_per_incident(a)
    assert loss
    net = eco.net_per_1000(replace(a, loss_per_incident=loss))["net"]
    assert net == pytest.approx(0, abs=5.0)
    # At the simulated loss of 61 no intervention rate up to 100% pays for an all-call workflow.
    assert eco.break_even_intervention_success(eco.Assumptions()) is None
    cheap = replace(eco.Assumptions(), loss_per_incident=5000.0)
    share = eco.break_even_intervention_success(cheap)
    assert share is not None and 0 < share <= 1
    net = eco.net_per_1000(replace(cheap, intervention_success_rate=share))["net"]
    assert net == pytest.approx(0, abs=5.0)


def test_corrected_view_is_negative_without_an_intervention_in_every_scenario():
    view = eco.corrected_view_of_report_scenarios()
    assert set(view) == {"A_all_calls_loss_61", "B_all_calls_loss_150", "C_targeted_40pct_loss_61"}
    for name, rows in view.items():
        assert rows["intervention_0pct"] < 0, name
        assert rows["intervention_0pct"] == rows["intervention_0pct_with_dispute_savings"]
        assert rows["intervention_50pct"] > rows["intervention_0pct"]


def test_full_report_lists_what_is_not_counted():
    report = eco.full_report()
    assert report["status"].startswith("ASSUMPTIONS ONLY")
    assert "flagged cash gaps" in report["not_counted"] and "closed cases" in report["not_counted"]
    assert len(report["sensitivity"]) == 3 * 4 * 3
