"""Tests for AgentAnomalyDetector (T019 / T023).

Verifies:
- Numeric X only fitting with volume-band boundaries learned from train quantiles
- Protected metadata invariance (changing region/agent_type in metadata never affects scores)
- Single-row versus batch scoring invariance (frozen train normalization)
- Protection of honest high-volume agents (low false-flag rate)
- Feature leakage guard enforcement
- Column mismatch and NaN rejection
- Metamorphic agent metadata invariance
- Explainability output adhering to docs/api-contracts.md GET /agents/{id}/risk
- Model persistence (save/load)
- Small deterministic synthetic fixture integration (never canonical final test artifacts)
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.data.config import ConfigError, load_config
from app.data.generator import build_canonical_agent_registry, generate_dataset_with_observations
from app.data.splits import allocate_cohorts
from app.features.guard import FeatureLeakageError
from app.ml.agent_model import AgentAnomalyDetector
from app.ml.features import extract_agent_features


@pytest.fixture
def synthetic_agent_dataset() -> tuple[
    pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
]:
    """Generate synthetic agent behavioral features split into disjoint train and validation."""
    rng = np.random.default_rng(42)

    def _make_agents(n_normal: int, n_honest: int, n_skimmer: int):
        types = (
            ["normal"] * n_normal
            + ["high_volume_honest"] * n_honest
            + ["skimmer"] * n_skimmer
        )
        rng.shuffle(types)

        fee_ratios = []
        daily_volumes = []
        allowance_ratios = []
        regions = []
        volume_bands = []

        for t in types:
            regions.append(rng.choice(["dhaka", "chittagong", "rajshahi", "khulna"]))
            if t == "skimmer":
                fee_ratios.append(rng.uniform(1.25, 1.55))
                daily_volumes.append(rng.uniform(30.0, 70.0))
                allowance_ratios.append(rng.uniform(1.0, 1.3))
                volume_bands.append("high")
            elif t == "high_volume_honest":
                fee_ratios.append(1.0)  # Honest: exactly official fee
                daily_volumes.append(rng.uniform(80.0, 150.0))  # High volume
                allowance_ratios.append(rng.uniform(2.0, 3.0))  # Big allowance spikes
                volume_bands.append("high")
            else:
                fee_ratios.append(rng.normal(1.0, 0.02))
                daily_volumes.append(rng.uniform(10.0, 40.0))
                allowance_ratios.append(rng.uniform(0.8, 1.2))
                volume_bands.append("standard")

        X = pd.DataFrame(
            {
                "agent_fee_ratio_over_official": np.maximum(fee_ratios, 1.0),
                "agent_volume_daily_mean": daily_volumes,
                "agent_allowance_day_volume_ratio": allowance_ratios,
            }
        )
        meta = pd.DataFrame({"region": regions, "volume_band": volume_bands, "agent_type": types})
        y = pd.Series([1 if t == "skimmer" else 0 for t in types], name="target")
        types_ser = pd.Series(types, name="agent_type")
        return X, y, meta, types_ser

    X_train, y_train, meta_train, _ = _make_agents(60, 10, 10)
    X_val, y_val, meta_val, types_val = _make_agents(30, 5, 5)

    return X_train, y_train, meta_train, X_val, y_val, meta_val, types_val


def test_agent_feature_leakage_rejection(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Ensure feature leakage guard stops forbidden columns."""
    X_train, _, meta_train, _, _, _, _ = synthetic_agent_dataset
    leaky_X = X_train.copy()
    leaky_X["agent_type"] = "skimmer"

    detector = AgentAnomalyDetector()
    with pytest.raises(FeatureLeakageError):
        detector.fit(leaky_X, meta_train)


def test_column_mismatch_and_nan_rejection(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify detector rejects column mismatches and NaNs in fit and score."""
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    # Missing column
    bad_cols_X = X_val.drop(columns=["agent_fee_ratio_over_official"])
    with pytest.raises(ValueError, match="Column mismatch"):
        detector.score_combined(bad_cols_X)

    # NaN in input
    nan_X = X_val.copy()
    nan_X.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN, infinite, or non-finite"):
        detector.score_combined(nan_X)


def test_protected_metadata_invariance(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Changing protected metadata (region) or ground-truth labels (agent_type)
    must have ZERO effect on computed scores or volume-band assignments.
    """
    X_train, _, meta_train, X_val, _, meta_val, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train, meta_train)

    # 1. Score with original metadata
    scores_orig, ctx_orig = detector.score_combined(X_val, meta_val)

    # 2. Score with completely altered metadata (all regions changed, agent types changed)
    altered_meta = meta_val.copy()
    altered_meta["region"] = "barishal"
    altered_meta["agent_type"] = "skimmer"
    altered_meta["volume_band"] = "generated_fake_band"

    scores_altered, ctx_altered = detector.score_combined(X_val, altered_meta)

    # 3. Score with None metadata
    scores_none, ctx_none = detector.score_combined(X_val, None)

    # Scores must be 100% identical regardless of metadata
    np.testing.assert_array_equal(scores_orig, scores_altered)
    np.testing.assert_array_equal(scores_orig, scores_none)

    # Peer group contexts must also be identical
    for c1, c2 in zip(ctx_orig, ctx_altered):
        assert c1["peer_group"] == c2["peer_group"]
        assert c1["peer_median"] == c2["peer_median"]


def test_single_row_versus_batch_scoring_invariance(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Single-row versus batch scores must be strictly identical because IF normalization
    and robust fee statistics are frozen from train, not computed on evaluated batches.
    """
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    # Batch scores
    batch_scores, _ = detector.score_combined(X_val)

    # Single-row scores evaluated one-by-one
    single_scores = []
    for i in range(len(X_val)):
        row = X_val.iloc[[i]]
        s_arr, _ = detector.score_combined(row)
        single_scores.append(float(s_arr[0]))

    np.testing.assert_allclose(batch_scores, np.array(single_scores), atol=1e-6)


def test_peer_robust_zscore_and_honest_protection(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify that peer robust Z-scores flag skimmers without penalizing honest agents."""
    X_train, _, _, X_val, _, _, types_val = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    z_risk, contexts = detector.score_peer_robust_zscore(X_val)
    assert len(z_risk) == len(X_val)
    assert len(contexts) == len(X_val)

    skimmer_indices = np.where(types_val == "skimmer")[0]
    honest_indices = np.where(types_val == "high_volume_honest")[0]

    skimmer_mean_risk = z_risk[skimmer_indices].mean()
    honest_mean_risk = z_risk[honest_indices].mean()

    assert skimmer_mean_risk > 0.70
    assert honest_mean_risk < 0.30


def test_isolation_forest_and_combined_scoring(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify Isolation Forest scoring and combined ensemble bounds in [0, 1]."""
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    if_scores = detector.score_isolation_forest(X_val)
    combined_scores, _ = detector.score_combined(X_val)

    assert len(if_scores) == len(X_val)
    assert len(combined_scores) == len(X_val)
    assert 0.0 <= combined_scores.min()
    assert combined_scores.max() <= 1.0


def test_explain_output_conforms_to_api_contract(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify explain output matches GET /agents/{id}/risk contract."""
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    row = X_val.iloc[0]
    explanation = detector.explain(agent_id="A_0042", X_row=row)

    assert explanation["agent_id"] == "A_0042"
    assert "risk" in explanation
    assert explanation["level"] in ("HIGH", "MEDIUM", "LOW")
    assert "reasons" in explanation
    assert len(explanation["reasons"]) >= 1
    assert "peer_group" in explanation
    assert explanation["model_version"] == "agent_anomaly_v1"


def test_evaluate_precision_at_k_and_false_flags(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify evaluation metrics: precision@k, recall, and false-flag rate on honest agents."""
    X_train, _, _, X_val, y_val, _, types_val = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    eval_results = detector.evaluate(
        X_val, y_val, agent_types=types_val, top_k=5
    )

    assert "peer_robust_zscore" in eval_results
    assert "isolation_forest" in eval_results
    assert "combined" in eval_results

    combined = eval_results["combined"]
    assert combined["precision_at_5"] >= 0.60
    assert combined["recall_on_skimmers"] >= 0.60
    assert combined["false_flag_rate_honest_high_volume"] == 0.0


def test_metamorphic_agent_demographic_invariance() -> None:
    """Metamorphic test: altering agent demographic slice (region) or agent_type
    leaves numeric X unchanged.
    """
    raw_agents = [
        {
            "agent_id": f"A_{i:03d}",
            "region": "dhaka",
            "volume_band": "standard",
            "agent_type": "normal",
        }
        for i in range(5)
    ]
    raw_txs = [
        {
            "txn_id": 100 + i,
            "user_id": f"U_{i:03d}",
            "agent_id": f"A_{i % 5:03d}",
            "txn_type": "cash_out",
            "amount": 2000.0,
            "fee": 30.0,
            "balance_after": 1000.0,
            "ts": "2026-10-02T10:00:00Z",
        }
        for i in range(25)
    ]

    X_orig, _, meta_orig, _ = extract_agent_features(raw_agents, raw_txs)

    altered_agents = [
        {
            "agent_id": f"A_{i:03d}",
            "region": "chittagong",
            "volume_band": "high",
            "agent_type": "skimmer",
        }
        for i in range(5)
    ]
    X_alt, _, meta_alt, _ = extract_agent_features(altered_agents, raw_txs)

    pd.testing.assert_frame_equal(X_orig, X_alt)
    assert not meta_orig.equals(meta_alt)


def test_model_save_and_load(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify agent detector serialization preserves frozen train state and restores
    exact scores.
    """
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = Path(tmpdir) / "agent_detector.joblib"
        detector.save(art_path)
        assert art_path.exists()

        loaded = AgentAnomalyDetector.load(art_path)
        orig_scores, _ = detector.score_combined(X_val)
        loaded_scores, _ = loaded.score_combined(X_val)

        np.testing.assert_allclose(orig_scores, loaded_scores, atol=1e-6)
        assert detector.volume_band_thresholds_ == loaded.volume_band_thresholds_
        assert detector.global_stats_ == loaded.global_stats_


def test_small_fixture_integration() -> None:
    """Integration test using small deterministic synthetic fixture (never canonical
    final split).
    """
    cfg = copy.deepcopy(load_config())
    cfg["simulation"]["customers"] = 300
    cfg["simulation"]["agents"] = 15
    cfg["simulation"]["agent_mix"] = {"normal": 10, "high_volume_honest": 3, "skimmers": 2}
    canonical_agents = build_canonical_agent_registry(cfg)
    cohort_agents = allocate_cohorts(cfg, canonical_agents=canonical_agents)

    train_data, _ = generate_dataset_with_observations(
        config=cfg,
        seed=cfg["simulation"]["seed_train"],
        agent_ids=cohort_agents["train"],
        customers=200,
        canonical_agents=canonical_agents,
    )
    val_data, _ = generate_dataset_with_observations(
        config=cfg,
        seed=cfg["simulation"]["seed_validation"],
        agent_ids=cohort_agents["validation"],
        customers=100,
        canonical_agents=canonical_agents,
    )

    X_train, y_train, meta_train, _ = extract_agent_features(
        train_data["agents"], train_data["transactions"]
    )
    X_val, y_val, meta_val, _ = extract_agent_features(
        val_data["agents"], val_data["transactions"]
    )

    detector = AgentAnomalyDetector()
    detector.fit(X_train, meta_train)

    top_k = min(len(val_data["agents"]), int(cfg["models"]["agent_anomaly"]["review_top_k"]))
    eval_res = detector.evaluate(X_val, y_val, agent_types=meta_val["agent_type"], top_k=top_k)

    assert eval_res["total_agents"] == len(val_data["agents"])
    assert "combined" in eval_res
    assert 0.0 <= eval_res["combined"][f"precision_at_{top_k}"] <= 1.0


def test_agent_detector_invalid_overrides() -> None:
    """Verify detector constructor and config reject invalid values."""
    with pytest.raises(ValueError):
        AgentAnomalyDetector(contamination=0.0)
    with pytest.raises(ValueError):
        AgentAnomalyDetector(contamination=0.6)
    with pytest.raises(ValueError):
        AgentAnomalyDetector(contamination=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AgentAnomalyDetector(peer_groups=["region"])
    with pytest.raises(ValueError):
        AgentAnomalyDetector(weight_z=0.8, weight_iforest=0.8)

    # Test invalid review_top_k via validated config dict
    cfg_bad_k = copy.deepcopy(load_config())
    cfg_bad_k["models"]["agent_anomaly"]["review_top_k"] = 0
    with pytest.raises((ConfigError, ValueError)):
        AgentAnomalyDetector(config=cfg_bad_k)

    cfg_bad_k_bool = copy.deepcopy(load_config())
    cfg_bad_k_bool["models"]["agent_anomaly"]["review_top_k"] = True
    with pytest.raises((ConfigError, ValueError)):
        AgentAnomalyDetector(config=cfg_bad_k_bool)


def test_agent_detector_explain_batch_rejection(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Explain requires exactly 1 row; batches must raise ValueError."""
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    with pytest.raises(ValueError, match="exactly 1 row"):
        detector.explain(agent_id="A_0042", X_row=X_val.iloc[:2])


def test_agent_detector_save_unfitted_rejection() -> None:
    """Saving an unfitted detector must raise ValueError."""
    detector = AgentAnomalyDetector()
    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = Path(tmpdir) / "unfitted.joblib"
        with pytest.raises(ValueError, match="Cannot save unfitted"):
            detector.save(art_path)


def test_agent_detector_rejected_refit_preserves_atomic_state(
    synthetic_agent_dataset: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series
    ],
) -> None:
    """Rejected refit must preserve existing fitted state and frozen train statistics."""
    X_train, _, _, X_val, _, _, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X_train)

    orig_scores, _ = detector.score_combined(X_val)
    orig_thresholds = detector.volume_band_thresholds_
    orig_global_stats = copy.deepcopy(detector.global_stats_)
    orig_schema = list(detector.feature_names_)

    # Rejected refit: NaN in input
    nan_X = X_train.copy()
    nan_X.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN, infinite, or non-finite"):
        detector.fit(nan_X)

    scores_after, _ = detector.score_combined(X_val)
    np.testing.assert_array_equal(orig_scores, scores_after)
    assert detector.volume_band_thresholds_ == orig_thresholds
    assert detector.global_stats_ == orig_global_stats
    assert detector.feature_names_ == orig_schema

    # Rejected refit: Missing required behavioral feature
    missing_X = X_train.drop(columns=["agent_fee_ratio_over_official"])
    with pytest.raises(ValueError, match="Missing required behavioral feature"):
        detector.fit(missing_X)

    scores_after2, _ = detector.score_combined(X_val)
    np.testing.assert_array_equal(orig_scores, scores_after2)
    assert detector.volume_band_thresholds_ == orig_thresholds
    assert detector.global_stats_ == orig_global_stats
    assert detector.feature_names_ == orig_schema

    # Fresh invalid fit stays unfitted and unsaveable
    fresh = AgentAnomalyDetector()
    with pytest.raises(ValueError):
        fresh.fit(nan_X)
    assert fresh.iforest is None
    assert fresh.feature_names_ == []
    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = Path(tmpdir) / "fresh_unfitted.joblib"
        with pytest.raises(ValueError, match="Cannot save unfitted"):
            fresh.save(art_path)
