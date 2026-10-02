"""Tests for AgentAnomalyDetector (T019).

Verifies:
- Peer robust Z-score by region and volume band
- Isolation Forest anomaly detection
- Combined ensemble scoring
- Protection of honest high-volume agents (low false-flag rate)
- Strict feature leakage guard assertion
- Explainability output adhering to docs/api-contracts.md GET /agents/{id}/risk
- Integration test on synthetic validation split
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.features.guard import FeatureLeakageError
from app.ml.agent_model import AgentAnomalyDetector
from app.ml.features import extract_agent_features


@pytest.fixture
def synthetic_agent_dataset() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Generate synthetic agent behavioral features with honest high-volume and skimmers."""
    rng = np.random.default_rng(42)

    # 10% skimmers, 10% high-volume honest, 80% normal
    types = ["normal"] * 80 + ["high_volume_honest"] * 10 + ["skimmer"] * 10
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

    peer_metadata = pd.DataFrame(
        {
            "region": regions,
            "volume_band": volume_bands,
        }
    )

    y = pd.Series([1 if t == "skimmer" else 0 for t in types], name="target")
    agent_types = pd.Series(types, name="agent_type")

    return X, y, peer_metadata, agent_types


def test_agent_feature_leakage_rejection(
    synthetic_agent_dataset: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
) -> None:
    """Ensure feature leakage guard stops forbidden columns."""
    X, y, peer_metadata, _ = synthetic_agent_dataset
    leaky_X = X.copy()
    leaky_X["agent_type"] = "skimmer"

    detector = AgentAnomalyDetector()
    with pytest.raises(FeatureLeakageError):
        detector.fit(leaky_X, peer_metadata)


def test_peer_robust_zscore_and_honest_protection(
    synthetic_agent_dataset: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
) -> None:
    """Verify that peer robust Z-scores flag skimmers without penalizing honest agents."""
    X, y, peer_metadata, agent_types = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X, peer_metadata)

    z_risk, contexts = detector.score_peer_robust_zscore(X, peer_metadata)
    assert len(z_risk) == len(X)
    assert len(contexts) == len(X)

    # Skimmers should have high risk
    skimmer_indices = np.where(agent_types == "skimmer")[0]
    honest_indices = np.where(agent_types == "high_volume_honest")[0]

    skimmer_mean_risk = z_risk[skimmer_indices].mean()
    honest_mean_risk = z_risk[honest_indices].mean()

    assert skimmer_mean_risk > 0.70
    # Honest high-volume agents have fee_ratio == 1.0, so risk must remain low
    assert honest_mean_risk < 0.30


def test_isolation_forest_and_combined_scoring(
    synthetic_agent_dataset: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
) -> None:
    """Verify Isolation Forest scoring and combined ensemble."""
    X, y, peer_metadata, agent_types = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X, peer_metadata)

    if_scores = detector.score_isolation_forest(X)
    combined_scores, _ = detector.score_combined(X, peer_metadata)

    assert len(if_scores) == len(X)
    assert len(combined_scores) == len(X)
    assert 0.0 <= combined_scores.min()
    assert combined_scores.max() <= 1.0


def test_explain_output_conforms_to_api_contract(
    synthetic_agent_dataset: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
) -> None:
    """Verify explain output matches GET /agents/{id}/risk contract."""
    X, y, peer_metadata, _ = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X, peer_metadata)

    row = X.iloc[0]
    p_row = peer_metadata.iloc[0]
    explanation = detector.explain(agent_id="A_0042", X_row=row, peer_row=p_row)

    assert explanation["agent_id"] == "A_0042"
    assert "risk" in explanation
    assert explanation["level"] in ("HIGH", "MEDIUM", "LOW")
    assert "reasons" in explanation
    assert len(explanation["reasons"]) >= 1
    assert "peer_group" in explanation
    assert explanation["model_version"] == "agent_anomaly_v1"


def test_evaluate_precision_at_k_and_false_flags(
    synthetic_agent_dataset: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series],
) -> None:
    """Verify evaluation metrics: precision@k, recall, and false-flag rate on honest agents."""
    X, y, peer_metadata, agent_types = synthetic_agent_dataset
    detector = AgentAnomalyDetector()
    detector.fit(X, peer_metadata)

    eval_results = detector.evaluate(
        X, y, peer_metadata=peer_metadata, agent_types=agent_types, top_k=10
    )

    assert "peer_robust_zscore" in eval_results
    assert "isolation_forest" in eval_results
    assert "combined" in eval_results

    combined = eval_results["combined"]
    assert combined["precision_at_10"] >= 0.70
    assert combined["recall_on_skimmers"] >= 0.70
    # Honest high-volume agents must not be flagged
    assert combined["false_flag_rate_honest_high_volume"] == 0.0


def test_validation_split_agent_anomaly_integration() -> None:
    """End-to-end integration test on synthetic validation split."""
    val_path = Path("data/generated/splits/validation.json")
    if not val_path.exists():
        val_path = Path("../data/generated/splits/validation.json")
    if not val_path.exists():
        pytest.skip("validation.json not found")

    with open(val_path, "r", encoding="utf-8") as f:
        val_data = json.load(f)

    agents = val_data["agents"]
    txs = val_data["transactions"]

    X, y, meta_df, _ = extract_agent_features(agents, txs)

    detector = AgentAnomalyDetector()
    detector.fit(X, meta_df)

    top_k = int(y.sum())
    eval_res = detector.evaluate(
        X, y, peer_metadata=meta_df, agent_types=meta_df["agent_type"], top_k=top_k
    )

    # In validation split, skimmers exist and should be detected with high precision
    assert eval_res["total_agents"] == len(agents)
    assert eval_res["total_skimmers"] > 0
    assert eval_res["combined"][f"precision_at_{top_k}"] >= 0.50
    assert eval_res["combined"]["recall_on_skimmers"] >= 0.50
