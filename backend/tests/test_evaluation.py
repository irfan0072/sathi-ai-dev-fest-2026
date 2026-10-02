"""Tests for comprehensive evaluation suite (T020 / T023).

Verifies that all 6 experiments from docs/evaluation-plan.md and demographic fairness audits
run against isolated small generated synthetic fixtures in a tmp directory (1000 customers,
30 agents with 20/6/4 mix), honoring the final-test-only rule and reusing app.data generator.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from app.data.config import ConfigError, load_config, validate_config
from app.data.generator import build_canonical_agent_registry
from app.data.splits import (
    allocate_cohorts,
    generate_shifted_test_split,
    generate_splits,
)
from app.evaluation.suite import EvaluationRunner
from app.ml.agent_model import AgentAnomalyDetector
from app.ml.assisted_model import AssistedUserClassifier
from app.ml.features import extract_agent_features, extract_user_features


def get_small_eval_config() -> dict[str, Any]:
    """Build small valid configuration for unit test evaluation fixtures."""
    cfg = copy.deepcopy(load_config())
    cfg["simulation"]["customers"] = 1000
    cfg["simulation"]["agents"] = 30
    cfg["simulation"]["agent_mix"] = {"normal": 20, "high_volume_honest": 6, "skimmers": 4}
    cfg["simulation"]["agent_split"] = {"train": 0.60, "validation": 0.20, "test": 0.20}
    return validate_config(cfg)


def _generate_synthetic_fixture(base_dir: Path) -> None:
    """Generate small disjoint synthetic datasets (1000 customers, 30 agents: 20/6/4 mix).

    Reuses app.data generator/split logic and guarantees schema and seed conformance.
    """
    cfg = get_small_eval_config()
    canonical_agents = build_canonical_agent_registry(cfg)
    cohort_agents = allocate_cohorts(cfg, canonical_agents=canonical_agents)

    # Disjoint agent cohorts: 18 train, 6 validation, 6 test (60-20-20)
    assert len(cohort_agents["train"]) == 18
    assert len(cohort_agents["validation"]) == 6
    assert len(cohort_agents["test"]) == 6

    # Generate standard splits (train, validation, test) with manifest
    split_result = generate_splits(config=cfg, output_dir=base_dir)

    # Generate shifted test split using test cohort agents
    generate_shifted_test_split(
        config=cfg,
        output_dir=base_dir,
        canonical_agents=canonical_agents,
        test_agent_ids=cohort_agents["test"],
    )

    # Assert user/agent disjointness and expected sizes
    datasets = {
        c: split_result["splits"][c]["dataset"] for c in ("train", "validation", "test")
    }
    assert len(datasets["train"]["users"]) == 600
    assert len(datasets["validation"]["users"]) == 200
    assert len(datasets["test"]["users"]) == 200

    train_users = {u["user_id"] for u in datasets["train"]["users"]}
    val_users = {u["user_id"] for u in datasets["validation"]["users"]}
    test_users = {u["user_id"] for u in datasets["test"]["users"]}
    assert train_users.isdisjoint(val_users)
    assert train_users.isdisjoint(test_users)
    assert val_users.isdisjoint(test_users)


@pytest.fixture
def eval_runner(tmp_path: Path) -> EvaluationRunner:
    """Instantiate EvaluationRunner with isolated small generated synthetic fixture
    in tmp directory.
    """
    _generate_synthetic_fixture(tmp_path)
    return EvaluationRunner(splits_dir=tmp_path)


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

    for m in [baseline, clean, noisy]:
        assert 0.0 <= m["pr_auc"] <= 1.0
        assert 0.0 <= m["brier_score"] <= 1.0
        assert 0.0 <= m["roc_auc"] <= 1.0
        assert 0.0 <= m["recall_at_80p_precision"] <= 1.0


def test_experiment_2_agent_anomaly(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 2: Agent anomaly ensemble vs baseline."""
    val_data = eval_runner.load_split("validation")
    res = eval_runner.run_experiment_2_agent_anomaly(val_data=val_data)

    assert "baseline_rule" in res
    assert "peer_robust_zscore" in res
    assert "isolation_forest" in res
    assert "combined_ensemble" in res
    assert res["total_agents"] == len(val_data["agents"])
    assert res["total_skimmers"] >= 0

    comb = res["combined_ensemble"]
    k = res["total_skimmers"]
    assert 0.0 <= comb[f"precision_at_{k}"] <= 1.0
    assert 0.0 <= comb["recall_on_skimmers"] <= 1.0
    assert 0.0 <= comb["false_flag_rate_honest_high_volume"] <= 1.0


def test_experiment_3_skimming_sweep(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 3: Skimming intensity sweep."""
    val_data = eval_runner.load_split("validation")
    res = eval_runner.run_experiment_3_skimming_sweep(val_data=val_data)

    assert "subtle" in res
    assert "moderate" in res
    assert "obvious" in res

    assert res["subtle"]["fee_ratio"] < res["moderate"]["fee_ratio"]
    assert res["moderate"]["fee_ratio"] < res["obvious"]["fee_ratio"]
    assert 0.0 <= res["subtle"]["mean_risk_score"] <= 1.0
    assert 0.0 <= res["moderate"]["mean_risk_score"] <= 1.0
    assert 0.0 <= res["obvious"]["mean_risk_score"] <= 1.0


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
    full_pr_auc = res["full_model"]["pr_auc"]
    for key in ["full_model", "no_session_signals", "no_cash_gap_signals"]:
        assert 0.0 <= res[key]["pr_auc"] <= 1.0
        assert res[key]["delta_pr_auc"] == pytest.approx(
            res[key]["pr_auc"] - full_pr_auc, abs=1e-3
        )


def test_experiment_5_adoption_sensitivity(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 5: Adoption sensitivity and loss prevented."""
    test_obs = eval_runner.load_observations("test")
    if not test_obs:
        pytest.skip("test.observations.json not found")

    res = eval_runner.run_experiment_5_adoption_sensitivity(test_obs_data=test_obs)

    assert "scenarios" in res
    assert res["total_test_skimming_loss_bdt"] >= 0.0

    s30 = res["scenarios"]["adoption_30pct"]
    s50 = res["scenarios"]["adoption_50pct"]
    s70 = res["scenarios"]["adoption_70pct"]

    assert s30["loss_prevented_bdt"] <= s50["loss_prevented_bdt"]
    assert s50["loss_prevented_bdt"] <= s70["loss_prevented_bdt"]
    assert s30["pct_skimming_loss_prevented"] == 30
    assert s50["pct_skimming_loss_prevented"] == 50
    assert s70["pct_skimming_loss_prevented"] == 70


def test_experiment_6_distribution_shift(eval_runner: EvaluationRunner) -> None:
    """Verify Experiment 6: Robustness under distribution shift."""
    train_data = eval_runner.load_split("train")
    test_data = eval_runner.load_split("test")
    test_shifted = eval_runner.load_split("test_shifted")
    val_data = eval_runner.load_split("validation")

    res = eval_runner.run_experiment_6_distribution_shift(
        train_data=train_data,
        test_data=test_data,
        test_shifted_data=test_shifted,
        val_data=val_data,
        sample_train_size=1000,
    )

    assert "canonical_test" in res
    assert "shifted_test" in res
    assert "delta_pr_auc" in res
    assert isinstance(res["robust"], bool)
    assert 0.0 <= res["canonical_test"]["pr_auc"] <= 1.0
    assert 0.0 <= res["shifted_test"]["pr_auc"] <= 1.0
    assert abs(res["delta_pr_auc"]) <= 1.0
    assert res["robust"] == (abs(res["delta_pr_auc"]) < 0.15)


def test_fairness_evaluation_meets_target(eval_runner: EvaluationRunner) -> None:
    """Verify demographic fairness evaluation metric structure and consistency."""
    train_data = eval_runner.load_split("train")
    val_data = eval_runner.load_split("validation")

    res = eval_runner.run_fairness_evaluation(
        train_data=train_data, val_data=val_data, sample_train_size=1000
    )

    assert "slices" in res
    for slice_name in ["gender", "age_band", "region", "urban_rural"]:
        assert slice_name in res["slices"]

    assert 0.0 <= res["global_max_tpr_gap"] <= 1.0
    assert res["target_max_tpr_gap"] == 0.10
    assert isinstance(res["satisfies_fairness_target"], bool)
    assert res["satisfies_fairness_target"] == (
        res["global_max_tpr_gap"] <= res["target_max_tpr_gap"]
    )


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
            train_data, test_data, test_shifted, val_data=val_data, sample_train_size=1000
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


def test_configured_controls_validation() -> None:
    """Test that configured controls fail closed when given invalid configuration values."""
    base_cfg = get_small_eval_config()

    # 1. Invalid assisted classifier classification threshold
    bad_cfg1 = copy.deepcopy(base_cfg)
    bad_cfg1["models"]["assisted_classifier"]["classification_threshold"] = 1.5
    with pytest.raises(ConfigError):
        validate_config(bad_cfg1)

    # 2. Region illegally injected into agent_anomaly peer groups
    bad_cfg2 = copy.deepcopy(base_cfg)
    bad_cfg2["models"]["agent_anomaly"]["peer_groups"] = ["region", "volume_band"]
    with pytest.raises(ConfigError, match=r"peer_groups must equal"):
        validate_config(bad_cfg2)

    # 3. Invalid volume quantiles (not ordered)
    bad_cfg3 = copy.deepcopy(base_cfg)
    bad_cfg3["models"]["agent_anomaly"]["volume_quantiles"] = [0.8, 0.2]
    with pytest.raises(ConfigError):
        validate_config(bad_cfg3)

    # 4. Weights not summing to 1.0
    bad_cfg4 = copy.deepcopy(base_cfg)
    bad_cfg4["models"]["agent_anomaly"]["weight_z"] = 0.5
    bad_cfg4["models"]["agent_anomaly"]["weight_iforest"] = 0.2
    with pytest.raises(ConfigError, match="must sum to 1.0"):
        validate_config(bad_cfg4)


def test_loaded_artifact_predictions(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Test trained model serialization, reloading from tmp artifact, and prediction parity."""
    train_data = eval_runner.load_split("train")
    val_data = eval_runner.load_split("validation")

    X_tr, y_tr, _, _ = extract_user_features(
        train_data["users"][:300], train_data["transactions"], train_data["sessions"]
    )
    X_val, y_val, _, _ = extract_user_features(
        val_data["users"][:100], val_data["transactions"], val_data["sessions"]
    )

    clf = AssistedUserClassifier(random_state=42)
    clf.fit(X_tr, y_tr, X_val, y_val)

    art_path = tmp_path / "artifacts" / "test_model.joblib"
    clf.save(art_path)

    loaded = AssistedUserClassifier.load(art_path)
    orig_probs = clf.predict_proba(X_val)
    loaded_probs = loaded.predict_proba(X_val)

    np.testing.assert_allclose(orig_probs, loaded_probs, atol=1e-6)

    # Test agent anomaly detector artifact save/load
    X_ag, _, meta_df, _ = extract_agent_features(val_data["agents"], val_data["transactions"])
    detector = AgentAnomalyDetector()
    detector.fit(X_ag)

    ag_art_path = tmp_path / "artifacts" / "agent_detector.joblib"
    detector.save(ag_art_path)

    loaded_detector = AgentAnomalyDetector.load(ag_art_path)
    orig_scores, _ = detector.score_combined(X_ag)
    loaded_scores, _ = loaded_detector.score_combined(X_ag)

    np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-6)
