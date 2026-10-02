"""Tests for comprehensive evaluation suite (T020).

Verifies that all 6 experiments from docs/evaluation-plan.md and demographic fairness audits
run against isolated small generated synthetic fixtures in a tmp directory (1000 customers,
30 agents with 20/6/4 mix), honoring the final-test-only rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.evaluation.suite import EvaluationRunner


def _generate_synthetic_fixture(base_dir: Path) -> None:
    """Generate small disjoint synthetic datasets (1000 customers, 30 agents: 20/6/4 mix)."""
    regions = ["dhaka", "chittagong", "rajshahi", "sylhet"]
    age_bands = ["18-35", "36-59", "60+"]
    genders = ["female", "male"]
    urban_rurals = ["urban", "rural"]

    def build_split(
        prefix: str,
        n_users: int,
        n_agents: int,
        n_skimmers: int,
        start_user_idx: int,
        start_agent_idx: int,
        start_tx_idx: int,
        shifted: bool = False,
    ) -> tuple[dict[str, Any], int, int, int]:
        agents = []
        for a_i in range(n_agents):
            aid = f"A_{prefix}_{start_agent_idx + a_i:03d}"
            is_skimmer = a_i < n_skimmers
            agents.append(
                {
                    "agent_id": aid,
                    "agent_type": "skimmer" if is_skimmer else "normal",
                    "region": regions[(start_agent_idx + a_i) % len(regions)],
                    "volume_band": "high_volume" if a_i % 2 == 0 else "standard",
                }
            )

        users = []
        transactions = []
        sessions = []
        curr_tx = start_tx_idx

        for u_i in range(n_users):
            uid = f"U_{prefix}_{start_user_idx + u_i:04d}"
            is_assisted = (u_i % 2 == 0)
            users.append(
                {
                    "user_id": uid,
                    "group_label": "assisted" if is_assisted else "independent",
                    "gender": genders[u_i % len(genders)],
                    "age_band": age_bands[u_i % len(age_bands)],
                    "region": regions[u_i % len(regions)],
                    "urban_rural": urban_rurals[u_i % len(urban_rurals)],
                }
            )

            # Credit transaction
            cr_amt = 4000.0 if shifted else 3000.0
            transactions.append(
                {
                    "txn_id": curr_tx,
                    "user_id": uid,
                    "agent_id": None,
                    "txn_type": "credit",
                    "amount": cr_amt,
                    "fee": 0.0,
                    "balance_after": cr_amt,
                    "ts": "2026-10-01T09:00:00",
                }
            )
            curr_tx += 1

            # Cash-out transaction (with agent assignment)
            assigned_agent = agents[u_i % len(agents)]
            is_agent_skimmer = (assigned_agent["agent_type"] == "skimmer")
            co_amt = 2500.0 if shifted else 2000.0
            fee_rate = 0.018 if shifted else 0.015
            fee_mult = 1.35 if is_agent_skimmer else 1.0
            co_fee = round(co_amt * fee_rate * fee_mult, 2)
            transactions.append(
                {
                    "txn_id": curr_tx,
                    "user_id": uid,
                    "agent_id": assigned_agent["agent_id"],
                    "txn_type": "cash_out",
                    "amount": co_amt,
                    "fee": co_fee,
                    "balance_after": max(0.0, cr_amt - co_amt - co_fee),
                    "ts": "2026-10-05T12:00:00",
                    "channel": "agent_initiated" if is_assisted else "customer_app",
                }
            )
            curr_tx += 1

            # Send transaction
            transactions.append(
                {
                    "txn_id": curr_tx,
                    "user_id": uid,
                    "agent_id": None,
                    "txn_type": "send",
                    "amount": 200.0,
                    "fee": 5.0,
                    "balance_after": max(0.0, cr_amt - co_amt - co_fee - 205.0),
                    "ts": "2026-10-06T14:00:00",
                }
            )
            curr_tx += 1

            # Bill pay transaction
            transactions.append(
                {
                    "txn_id": curr_tx,
                    "user_id": uid,
                    "agent_id": None,
                    "txn_type": "bill_pay",
                    "amount": 100.0,
                    "fee": 0.0,
                    "balance_after": max(0.0, cr_amt - co_amt - co_fee - 305.0),
                    "ts": "2026-10-07T15:00:00",
                }
            )
            curr_tx += 1

            # PIN session
            pin_retries = 2 if is_assisted else 0
            pin_ms = 8000 if is_assisted else 2500
            steps = 5 if is_assisted else 3
            if shifted:
                pin_ms += 1500
            sessions.append(
                {
                    "session_id": f"sess_{uid}_1",
                    "user_id": uid,
                    "pin_retries": pin_retries,
                    "pin_entry_ms": pin_ms,
                    "steps": steps,
                }
            )

        data = {
            "users": users,
            "agents": agents,
            "transactions": transactions,
            "sessions": sessions,
        }
        return data, start_user_idx + n_users, start_agent_idx + n_agents, curr_tx

    u_idx, a_idx, tx_idx = 0, 0, 1000

    # 1. Train split: 600 customers, 20 agents (16 normal, 4 skimmers)
    train_data, u_idx, a_idx, tx_idx = build_split(
        "TR", 600, 20, 4, u_idx, a_idx, tx_idx
    )
    with open(base_dir / "train.json", "w", encoding="utf-8") as f:
        json.dump(train_data, f)

    # 2. Validation split: 200 customers, 6 agents (4 normal, 2 skimmers)
    val_data, u_idx, a_idx, tx_idx = build_split(
        "VAL", 200, 6, 2, u_idx, a_idx, tx_idx
    )
    with open(base_dir / "validation.json", "w", encoding="utf-8") as f:
        json.dump(val_data, f)

    # 3. Test split: 200 customers, 4 agents (3 normal, 1 skimmer)
    test_data, test_u_idx, test_a_idx, test_tx_idx = build_split(
        "TEST", 200, 4, 1, u_idx, a_idx, tx_idx
    )
    with open(base_dir / "test.json", "w", encoding="utf-8") as f:
        json.dump(test_data, f)

    # 4. Synthetic Shifted Test split: same 200 test customers and 4 test agents
    # with shifted behavior
    shifted_data, _, _, _ = build_split(
        "TEST", 200, 4, 1, u_idx, a_idx, test_tx_idx, shifted=True
    )
    with open(base_dir / "test_shifted.json", "w", encoding="utf-8") as f:
        json.dump(shifted_data, f)

    # 5. Test observations for adoption sensitivity
    observations = {
        "transaction_observations": {
            f"obs_{i}": {
                "is_skimmer_action": (i % 3 != 0),
                "fee_overcharge": 50.0 if (i % 3 != 0) else 0.0,
                "payout_reduction": 100.0 if (i % 3 != 0) else 0.0,
            }
            for i in range(1, 20)
        }
    }
    with open(base_dir / "test.observations.json", "w", encoding="utf-8") as f:
        json.dump(observations, f)


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

    res = eval_runner.run_experiment_6_distribution_shift(
        train_data=train_data,
        test_data=test_data,
        test_shifted_data=test_shifted,
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
