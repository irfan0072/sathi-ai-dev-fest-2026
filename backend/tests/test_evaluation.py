"""Tests for comprehensive evaluation suite (T020).

Verifies that all 6 experiments from docs/evaluation-plan.md and demographic fairness audits:
1. Assisted User Classifier vs Rule Baseline (clean and 5% label noise)
2. Agent Anomaly Ensemble vs Rule Baseline
3. Skimming intensity sweep
4. Feature signal ablations
5. Adoption sensitivity and simulated loss prevented (BDT)
6. Robustness under distribution shift (test.json vs test_shifted.json)
7. Demographic fairness audit (max TPR gap <= 0.10)
8. Markdown report generation adhering to docs/report-outline.md
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.evaluation.suite import EvaluationRunner


@pytest.fixture
def eval_runner() -> EvaluationRunner:
    """Instantiate EvaluationRunner with local splits directory."""
    cwd = Path.cwd()
    splits_candidates = [
        cwd / "data" / "generated" / "splits",
        cwd.parent / "data" / "generated" / "splits",
    ]
    for p in splits_candidates:
        if p.exists() and (p / "validation.json").exists():
            return EvaluationRunner(splits_dir=p)
    pytest.skip("data/generated/splits directory not found")


def test_experiment_1_assisted_detection(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 1: Baseline vs LightGBM assisted user detection."""
    val_data = eval_runner.load_split("validation")
    train_data = eval_runner.load_split("train")

    res = eval_runner.run_experiment_1_assisted_detection(
        train_data=train_data, val_data=val_data, sample_train_size=1000
    )

    assert "baseline" in res
    assert "lightgbm_clean" in res
    assert "lightgbm_5pct_label_noise" in res

    baseline = res["baseline"]
    clean = res["lightgbm_clean"]
    noisy = res["lightgbm_5pct_label_noise"]

    assert clean["pr_auc"] >= baseline["pr_auc"]
    assert clean["pr_auc"] <= 0.98  # Sanity check constraint
    assert clean["brier_score"] <= baseline["brier_score"]  # Better calibration
    assert clean["recall_at_80p_precision"] > 0.0
    assert noisy["pr_auc"] > 0.70  # Resilient to 5% label noise


def test_experiment_2_agent_anomaly(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 2: Agent anomaly ensemble vs baseline."""
    val_data = eval_runner.load_split("validation")
    res = eval_runner.run_experiment_2_agent_anomaly(val_data=val_data)

    assert "baseline_rule" in res
    assert "peer_robust_zscore" in res
    assert "isolation_forest" in res
    assert "combined_ensemble" in res

    comb = res["combined_ensemble"]
    k = res["total_skimmers"]
    assert comb[f"precision_at_{k}"] >= 0.50
    assert comb["recall_on_skimmers"] >= 0.50
    assert comb["false_flag_rate_honest_high_volume"] == 0.0


def test_experiment_3_skimming_sweep(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 3: Skimming intensity sweep."""
    val_data = eval_runner.load_split("validation")
    res = eval_runner.run_experiment_3_skimming_sweep(val_data=val_data)

    assert "subtle" in res
    assert "moderate" in res
    assert "obvious" in res

    assert res["subtle"]["fee_ratio"] < res["moderate"]["fee_ratio"]
    assert res["moderate"]["fee_ratio"] < res["obvious"]["fee_ratio"]
    assert res["obvious"]["mean_risk_score"] >= res["subtle"]["mean_risk_score"]


def test_experiment_4_signal_ablations(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 4: Signal ablations."""
    train_data = eval_runner.load_split("train")
    val_data = eval_runner.load_split("validation")

    res = eval_runner.run_experiment_4_signal_ablations(
        train_data=train_data, val_data=val_data, sample_train_size=1000
    )

    assert "full_model" in res
    assert "no_session_signals" in res
    assert "no_cash_gap_signals" in res
    assert res["full_model"]["pr_auc"] > 0.70


def test_experiment_5_adoption_sensitivity(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 5: Adoption sensitivity and loss prevented."""
    test_obs = eval_runner.load_observations("test")
    if not test_obs:
        pytest.skip("test.observations.json not found")

    res = eval_runner.run_experiment_5_adoption_sensitivity(test_obs_data=test_obs)

    assert "scenarios" in res
    assert res["total_test_skimming_loss_bdt"] > 0.0

    s30 = res["scenarios"]["adoption_30pct"]
    s50 = res["scenarios"]["adoption_50pct"]
    s70 = res["scenarios"]["adoption_70pct"]

    assert s30["loss_prevented_bdt"] < s50["loss_prevented_bdt"]
    assert s50["loss_prevented_bdt"] < s70["loss_prevented_bdt"]
    assert s50["pct_skimming_loss_prevented"] == 50


def test_experiment_6_distribution_shift(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 6: Robustness under distribution shift."""
    train_data = eval_runner.load_split("train")
    test_data = eval_runner.load_split("test")
    test_shifted = eval_runner.load_split("test_shifted")

    res = eval_runner.run_experiment_6_distribution_shift(
        train_data=train_data,
        test_data=test_data,
        test_shifted_data=test_shifted,
        sample_train_size=1000,
    )

    assert "canonical_test" in res
    assert "shifted_test" in res
    assert "delta_pr_auc" in res
    assert res["robust"] is True
    assert res["canonical_test"]["pr_auc"] > 0.70
    assert res["shifted_test"]["pr_auc"] > 0.70


def test_fairness_evaluation_meets_target(eval_runner: EvaluationRunner) -> None:
    """Verify demographic fairness evaluation satisfies max_tpr_gap <= 0.10."""
    train_data = eval_runner.load_split("train")
    val_data = eval_runner.load_split("validation")

    res = eval_runner.run_fairness_evaluation(
        train_data=train_data, val_data=val_data, sample_train_size=1000
    )

    assert "slices" in res
    assert "gender" in res["slices"]
    assert "age_band" in res["slices"]
    assert "region" in res["slices"]
    assert "urban_rural" in res["slices"]

    assert res["satisfies_fairness_target"] is True
    assert res["global_max_tpr_gap"] <= res["target_max_tpr_gap"]


def test_markdown_report_generation(eval_runner: EvaluationRunner) -> None:
    """Verify markdown report generation produces valid tables."""
    val_data = eval_runner.load_split("validation")
    train_data = eval_runner.load_split("train")
    test_data = eval_runner.load_split("test")
    test_obs = eval_runner.load_observations("test")
    test_shifted = eval_runner.load_split("test_shifted")

    results = {
        "experiment_1_assisted_detection": eval_runner.run_experiment_1_assisted_detection(
            train_data, val_data, sample_train_size=1000
        ),
        "experiment_2_agent_anomaly": eval_runner.run_experiment_2_agent_anomaly(val_data),
        "experiment_3_skimming_sweep": eval_runner.run_experiment_3_skimming_sweep(val_data),
        "experiment_4_signal_ablations": eval_runner.run_experiment_4_signal_ablations(
            train_data, val_data, sample_train_size=1000
        ),
        "experiment_5_adoption_sensitivity": eval_runner.run_experiment_5_adoption_sensitivity(
            test_obs
        ),
        "experiment_6_distribution_shift": eval_runner.run_experiment_6_distribution_shift(
            train_data, test_data, test_shifted, sample_train_size=1000
        ),
        "fairness_evaluation": eval_runner.run_fairness_evaluation(
            train_data, val_data, sample_train_size=1000
        ),
    }

    report = eval_runner.generate_markdown_report(results)
    assert "# Sathi Evaluation & Experimentation Results" in report
    assert "## 1. Assisted-User Classifier vs Rule Baseline" in report
    assert "## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison" in report
    assert "## 3. Skimming Intensity Sweep" in report
    assert "## 4. Behavioral Feature Signal Ablations" in report
    assert "## 5. Adoption Sensitivity & Simulated Loss Prevented" in report
    assert "## 6. Robustness under Distribution Shift" in report
    assert "## 7. Demographic Fairness Audit" in report
    assert "Slice Disparity Gaps:" in report
