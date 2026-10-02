"""Tests for deterministic rule-based baselines (T016).

Verifies:
- AssistedUserRuleBaseline logic (top_share >= 0.70 & delay <= 24h)
- AgentAnomalyRuleBaseline logic (fee_ratio >= 1.2x)
- Strict feature leakage guard assertion (rejection of protected/ground-truth columns)
- Metric computations (Precision, Recall, F1, PR-AUC, Brier score)
- Demographic slice fairness calculations
- Config-driven threshold loading from data/config.yaml
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app.features.guard import FeatureLeakageError
from app.ml.baselines import (
    AgentAnomalyRuleBaseline,
    AssistedUserRuleBaseline,
    load_config_baselines,
)


@pytest.fixture
def clean_user_features() -> pd.DataFrame:
    """Fixture providing compliant user feature matrix."""
    return pd.DataFrame(
        {
            "top_agent_share": [0.85, 0.40, 0.75, 0.20],
            "credit_to_cashout_hours_mean": [8.0, 72.0, 48.0, 12.0],
            "top_agent_concentration": [0.75, 0.30, 0.60, 0.15],
            "cash_out_tx_count": [6.0, 5.0, 8.0, 3.0],
            "cash_out_total_amount": [18000.0, 12000.0, 24000.0, 6000.0],
            "cash_out_amount_mean": [3000.0, 2400.0, 3000.0, 2000.0],
            "cash_out_amount_median": [3000.0, 2400.0, 3000.0, 2000.0],
            "cash_out_amount_std": [100.0, 200.0, 150.0, 50.0],
            "cash_out_amount_min": [2800.0, 2000.0, 2800.0, 1900.0],
            "cash_out_amount_max": [3200.0, 2800.0, 3200.0, 2100.0],
            "credit_tx_count": [6.0, 3.0, 6.0, 2.0],
            "credit_total_amount": [18000.0, 15000.0, 24000.0, 6000.0],
            "credit_amount_mean": [3000.0, 5000.0, 4000.0, 3000.0],
            "credit_to_cashout_hours_min": [4.0, 48.0, 36.0, 8.0],
            "credit_to_cashout_hours_median": [8.0, 72.0, 48.0, 12.0],
            "withdrawn_balance_ratio_mean": [0.90, 0.40, 0.85, 0.30],
            "withdrawn_balance_ratio_max": [0.95, 0.50, 0.90, 0.40],
            "balance_end": [500.0, 4000.0, 800.0, 3500.0],
            "balance_mean": [1200.0, 4500.0, 1500.0, 3800.0],
            "balance_min": [200.0, 2000.0, 300.0, 1500.0],
            "pin_retries_total": [3.0, 0.0, 2.0, 0.0],
            "pin_retries_mean": [0.5, 0.0, 0.25, 0.0],
            "pin_retries_max": [1.0, 0.0, 1.0, 0.0],
            "pin_entry_seconds_mean": [14.0, 5.0, 12.0, 6.0],
            "pin_entry_seconds_median": [14.0, 5.0, 12.0, 6.0],
            "pin_entry_seconds_std": [2.0, 0.5, 1.5, 0.5],
            "session_steps_mean": [7.0, 4.0, 7.0, 4.0],
            "session_steps_max": [7.0, 4.0, 7.0, 4.0],
            "service_diversity_count": [1.0, 3.0, 1.0, 2.0],
            "send_tx_count": [0.0, 4.0, 0.0, 2.0],
            "send_total_amount": [0.0, 8000.0, 0.0, 3000.0],
            "bill_pay_tx_count": [0.0, 2.0, 0.0, 1.0],
            "bill_pay_total_amount": [0.0, 3000.0, 0.0, 1000.0],
            "agent_assisted_tx_ratio": [1.0, 0.2, 0.9, 0.3],
            "fee_total_paid": [270.0, 180.0, 360.0, 90.0],
            "fee_to_amount_ratio": [0.015, 0.015, 0.015, 0.015],
        }
    )


@pytest.fixture
def clean_agent_features() -> pd.DataFrame:
    """Fixture providing compliant agent feature matrix."""
    return pd.DataFrame(
        {
            "agent_fee_ratio_over_official": [1.0, 1.35, 1.05, 1.45],
            "agent_volume_daily_mean": [25.0, 60.0, 15.0, 45.0],
            "agent_allowance_day_volume_ratio": [1.0, 1.1, 1.0, 1.2],
        }
    )


def test_config_loading_baselines() -> None:
    """Verify that thresholds match data/config.yaml."""
    cfg = load_config_baselines()
    assert "assisted_rule" in cfg
    assert cfg["assisted_rule"]["top_agent_share_min"] == 0.7
    assert cfg["assisted_rule"]["hours_credit_to_cashout_max"] == 24.0
    assert "agent_rule" in cfg
    assert cfg["agent_rule"]["fee_ratio_over_official_min"] == 1.2


def test_assisted_user_rule_predictions(clean_user_features: pd.DataFrame) -> None:
    """Assisted user rule requires BOTH top_agent_share >= 0.70 AND delay <= 24h."""
    baseline = AssistedUserRuleBaseline()
    preds = baseline.predict(clean_user_features)

    # Row 0: share=0.85 (>=0.7), delay=8h (<=24) -> 1 (assisted)
    assert preds[0] == 1
    # Row 1: share=0.40 (<0.7), delay=72h (>24) -> 0 (independent)
    assert preds[1] == 0
    # Row 2: share=0.75 (>=0.7), delay=48h (>24) -> 0 (fails delay test)
    assert preds[2] == 0
    # Row 3: share=0.20 (<0.7), delay=12h (<=24) -> 0 (fails share test)
    assert preds[3] == 0


def test_assisted_user_leakage_guard_rejection() -> None:
    """Baseline must reject forbidden columns (e.g. group_label, gender)."""
    baseline = AssistedUserRuleBaseline()
    leaky_df = pd.DataFrame(
        {
            "top_agent_share": [0.8],
            "credit_to_cashout_hours_mean": [10.0],
            "group_label": ["assisted_allowance"],  # FORBIDDEN!
        }
    )
    with pytest.raises(FeatureLeakageError):
        baseline.predict(leaky_df)

    leaky_demo = pd.DataFrame(
        {
            "top_agent_share": [0.8],
            "credit_to_cashout_hours_mean": [10.0],
            "gender": ["female"],  # FORBIDDEN!
        }
    )
    with pytest.raises(FeatureLeakageError):
        baseline.predict(leaky_demo)


def test_assisted_user_evaluation_and_fairness(clean_user_features: pd.DataFrame) -> None:
    """Verify evaluation metric calculations and slice breakdowns."""
    baseline = AssistedUserRuleBaseline()
    y_true = np.array([1, 0, 1, 0])
    slices = pd.DataFrame(
        {
            "gender": ["female", "male", "female", "male"],
            "age_band": ["60+", "26-40", "41-60", "18-25"],
            "region": ["dhaka", "chittagong", "dhaka", "rajshahi"],
            "urban_rural": ["rural", "urban", "rural", "urban"],
        }
    )

    metrics = baseline.evaluate(clean_user_features, y_true, slices=slices)
    assert "accuracy" in metrics
    assert "precision" in metrics
    assert "recall" in metrics
    assert "f1" in metrics
    assert "pr_auc" in metrics
    assert "slices" in metrics
    assert "gender" in metrics["slices"]
    assert "max_tpr_gap" in metrics["slices"]["gender"]


def test_agent_rule_predictions(clean_agent_features: pd.DataFrame) -> None:
    """Agent rule flags agents when fee_ratio >= 1.2."""
    baseline = AgentAnomalyRuleBaseline(fee_ratio_over_official_min=1.2)
    preds = baseline.predict(clean_agent_features)

    # Row 0: ratio=1.00 (<1.2) -> 0 (normal)
    assert preds[0] == 0
    # Row 1: ratio=1.35 (>=1.2) -> 1 (skimmer)
    assert preds[1] == 1
    # Row 2: ratio=1.05 (<1.2) -> 0 (normal)
    assert preds[2] == 0
    # Row 3: ratio=1.45 (>=1.2) -> 1 (skimmer)
    assert preds[3] == 1


def test_agent_rule_leakage_guard_rejection() -> None:
    """Agent baseline must reject forbidden columns (e.g. agent_type)."""
    baseline = AgentAnomalyRuleBaseline()
    leaky_df = pd.DataFrame(
        {
            "agent_fee_ratio_over_official": [1.4],
            "agent_type": ["skimmer"],  # FORBIDDEN!
        }
    )
    with pytest.raises(FeatureLeakageError):
        baseline.predict(leaky_df)


def test_agent_rule_evaluation(clean_agent_features: pd.DataFrame) -> None:
    """Verify precision@k and anomaly ranking for agents."""
    baseline = AgentAnomalyRuleBaseline()
    y_true = np.array([0, 1, 0, 1])
    res = baseline.evaluate(clean_agent_features, y_true, top_k=2)

    assert res["model"] == "agent_rule_baseline"
    assert res["precision_at_2"] == 1.0  # Top 2 scores are rows 3 and 1, both true skimmers!
    assert res["flagged_count"] == 2
    assert res["total_agents"] == 4
