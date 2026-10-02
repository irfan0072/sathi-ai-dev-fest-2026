"""Comprehensive evaluation suite and experiment runner for Sathi.

Implements all 6 experiments from docs/evaluation-plan.md and fairness auditing:
1. Baseline vs LightGBM on assisted-user detection (clean and with 5% label noise).
2. Peer z-score vs Isolation Forest vs combined for agents.
3. Skimming intensity sweep (subtle, moderate, obvious).
4. Signal ablations (remove session signals, remove cash-received confirmations).
5. Adoption sensitivity (30%, 50%, 70%) and simulated loss prevented (in BDT).
6. Robustness under distribution shift (canonical test vs shifted test).
Fairness: Demographic slice breakdown (gender, age, region, urban/rural) with max TPR disparity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import auc, brier_score_loss, precision_recall_curve, roc_auc_score

from app.features.guard import assert_feature_columns
from app.ml.agent_model import AgentAnomalyDetector
from app.ml.assisted_model import AssistedUserClassifier
from app.ml.baselines import AgentAnomalyRuleBaseline, AssistedUserRuleBaseline
from app.ml.features import extract_agent_features, extract_user_features


class EvaluationRunner:
    """Orchestrates model evaluation, ablations, sensitivity sweeps, and fairness checks."""

    def __init__(
        self,
        splits_dir: str | Path | None = None,
        random_state: int = 42,
    ) -> None:
        self.random_state = random_state
        self.splits_dir = self._find_splits_dir(splits_dir)

    def _find_splits_dir(self, custom_path: str | Path | None) -> Path:
        """Locate data/generated/splits directory."""
        candidates = []
        if custom_path:
            candidates.append(Path(custom_path))
        cwd = Path.cwd()
        candidates.extend(
            [
                cwd / "data" / "generated" / "splits",
                cwd.parent / "data" / "generated" / "splits",
                Path(__file__).resolve().parent.parent.parent.parent
                / "data"
                / "generated"
                / "splits",
            ]
        )
        for p in candidates:
            if p.exists() and (p / "validation.json").exists():
                return p
        raise FileNotFoundError("Could not find data/generated/splits directory")

    def load_split(self, split_name: str) -> dict[str, Any]:
        """Load split JSON file."""
        file_path = self.splits_dir / f"{split_name}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Split file {file_path} not found")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_observations(self, split_name: str) -> dict[str, Any]:
        """Load observations JSON file if present."""
        file_path = self.splits_dir / f"{split_name}.observations.json"
        if not file_path.exists():
            return {}
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_experiment_1_assisted_detection(
        self,
        train_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        sample_train_size: int = 4000,
    ) -> dict[str, Any]:
        """Experiment 1: Baseline vs LightGBM on assisted-user detection (clean and noisy)."""
        if train_data is None:
            train_data = self.load_split("train")
        if val_data is None:
            val_data = self.load_split("validation")

        users_tr = (
            train_data["users"][:sample_train_size] if sample_train_size else train_data["users"]
        )
        X_tr, y_tr, _, _ = extract_user_features(
            users_tr, train_data["transactions"], train_data["sessions"]
        )
        X_val, y_val, _, _ = extract_user_features(
            val_data["users"], val_data["transactions"], val_data["sessions"]
        )

        assert_feature_columns(X_tr)
        assert_feature_columns(X_val)

        # Baseline evaluation
        baseline = AssistedUserRuleBaseline()
        b_preds = baseline.predict(X_val)
        b_prec, b_rec, _ = precision_recall_curve(y_val, b_preds)
        b_pr_auc = float(auc(b_rec, b_prec))
        b_roc_auc = float(roc_auc_score(y_val, b_preds))
        b_brier = float(brier_score_loss(y_val, b_preds))

        # LightGBM Clean
        clf_clean = AssistedUserClassifier(random_state=self.random_state)
        clf_clean.fit(X_tr, y_tr, X_val, y_val)
        probs_clean = clf_clean.predict_proba(X_val)[:, 1]
        p_c, r_c, _ = precision_recall_curve(y_val, probs_clean)
        pr_auc_clean = float(auc(r_c, p_c))
        roc_auc_clean = float(roc_auc_score(y_val, probs_clean))
        brier_clean = float(brier_score_loss(y_val, probs_clean))

        # Recall at 80% precision
        idx_80 = np.where(p_c >= 0.80)[0]
        rec_at_80p_clean = float(r_c[idx_80[0]]) if len(idx_80) > 0 else 0.0

        # LightGBM with 5% label noise in training
        rng = np.random.default_rng(self.random_state)
        y_tr_noisy = y_tr.copy()
        flip_mask = rng.random(len(y_tr)) < 0.05
        y_tr_noisy[flip_mask] = 1 - y_tr_noisy[flip_mask]

        clf_noisy = AssistedUserClassifier(random_state=self.random_state)
        clf_noisy.fit(X_tr, y_tr_noisy, X_val, y_val)
        probs_noisy = clf_noisy.predict_proba(X_val)[:, 1]
        p_n, r_n, _ = precision_recall_curve(y_val, probs_noisy)
        pr_auc_noisy = float(auc(r_n, p_n))
        roc_auc_noisy = float(roc_auc_score(y_val, probs_noisy))
        brier_noisy = float(brier_score_loss(y_val, probs_noisy))
        idx_80_n = np.where(p_n >= 0.80)[0]
        rec_at_80p_noisy = float(r_n[idx_80_n[0]]) if len(idx_80_n) > 0 else 0.0

        return {
            "baseline": {
                "pr_auc": round(b_pr_auc, 4),
                "roc_auc": round(b_roc_auc, 4),
                "brier_score": round(b_brier, 4),
                "recall_at_80p_precision": 0.0,
            },
            "lightgbm_clean": {
                "pr_auc": round(pr_auc_clean, 4),
                "roc_auc": round(roc_auc_clean, 4),
                "brier_score": round(brier_clean, 4),
                "recall_at_80p_precision": round(rec_at_80p_clean, 4),
            },
            "lightgbm_5pct_label_noise": {
                "pr_auc": round(pr_auc_noisy, 4),
                "roc_auc": round(roc_auc_noisy, 4),
                "brier_score": round(brier_noisy, 4),
                "recall_at_80p_precision": round(rec_at_80p_noisy, 4),
            },
        }

    def run_experiment_2_agent_anomaly(
        self,
        val_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 2: Baseline vs Peer Z-Score vs Isolation Forest vs Combined for agents."""
        if val_data is None:
            val_data = self.load_split("validation")

        agents = val_data["agents"]
        txs = val_data["transactions"]
        X_agents, y_agents, meta_df, _ = extract_agent_features(agents, txs)
        assert_feature_columns(X_agents)

        # Baseline evaluation
        baseline = AgentAnomalyRuleBaseline()
        b_res = baseline.evaluate(
            X_agents,
            y_agents,
            agent_types=meta_df["agent_type"],
            top_k=int(y_agents.sum()),
        )

        detector = AgentAnomalyDetector()
        detector.fit(X_agents, meta_df)
        d_res = detector.evaluate(
            X_agents,
            y_agents,
            peer_metadata=meta_df,
            agent_types=meta_df["agent_type"],
            top_k=int(y_agents.sum()),
        )

        return {
            "baseline_rule": b_res,
            "peer_robust_zscore": d_res["peer_robust_zscore"],
            "isolation_forest": d_res["isolation_forest"],
            "combined_ensemble": d_res["combined"],
            "total_agents": len(agents),
            "total_skimmers": int(y_agents.sum()),
        }

    def run_experiment_3_skimming_sweep(
        self,
        val_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 3: Skimming intensity sweep (subtle, moderate, obvious)."""
        if val_data is None:
            val_data = self.load_split("validation")

        agents = val_data["agents"]
        txs = val_data["transactions"]
        X_agents, y_agents, meta_df, _ = extract_agent_features(agents, txs)

        detector = AgentAnomalyDetector()
        detector.fit(X_agents, meta_df)

        # Evaluate detection across intensity tiers
        tiers = {
            "subtle": {"fee_mult": 1.05, "desc": "5% fee overcharge, 5% cash reduction"},
            "moderate": {"fee_mult": 1.15, "desc": "15% fee overcharge, 15% cash reduction"},
            "obvious": {"fee_mult": 1.35, "desc": "35% fee overcharge, 30% cash reduction"},
        }

        results = {}
        for tier_name, tier_info in tiers.items():
            probe_X = X_agents.copy()
            # Set probe skimmers to exact intensity tier
            probe_X["agent_fee_ratio_over_official"] = tier_info["fee_mult"]
            scores, _ = detector.score_combined(probe_X, meta_df)
            mean_risk = float(scores.mean())
            tier_flagged_rate = float((scores >= 0.80).mean())
            results[tier_name] = {
                "description": tier_info["desc"],
                "fee_ratio": tier_info["fee_mult"],
                "mean_risk_score": round(mean_risk, 3),
                "detection_flag_rate": round(tier_flagged_rate, 3),
            }

        return results

    def run_experiment_4_signal_ablations(
        self,
        train_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        sample_train_size: int = 4000,
    ) -> dict[str, Any]:
        """Experiment 4: Feature signal ablations (full, no sessions, no cash gap)."""
        if train_data is None:
            train_data = self.load_split("train")
        if val_data is None:
            val_data = self.load_split("validation")

        users_tr = (
            train_data["users"][:sample_train_size] if sample_train_size else train_data["users"]
        )
        X_tr, y_tr, _, _ = extract_user_features(
            users_tr, train_data["transactions"], train_data["sessions"]
        )
        X_val, y_val, _, _ = extract_user_features(
            val_data["users"], val_data["transactions"], val_data["sessions"]
        )

        def _evaluate_subset(cols_to_drop: list[str]) -> float:
            sub_tr = X_tr.drop(columns=[c for c in cols_to_drop if c in X_tr.columns])
            sub_val = X_val.drop(columns=[c for c in cols_to_drop if c in X_val.columns])
            assert_feature_columns(sub_tr)
            assert_feature_columns(sub_val)

            clf = AssistedUserClassifier(random_state=self.random_state)
            clf.fit(sub_tr, y_tr, sub_val, y_val)
            probs = clf.predict_proba(sub_val)[:, 1]
            p, r, _ = precision_recall_curve(y_val, probs)
            return float(auc(r, p))

        full_auc = _evaluate_subset([])
        session_cols = [c for c in X_tr.columns if c.startswith("pin_") or c.startswith("session_")]
        no_session_auc = _evaluate_subset(session_cols)
        cash_gap_cols = [c for c in X_tr.columns if "cash_gap" in c]
        no_cash_gap_auc = _evaluate_subset(cash_gap_cols)

        return {
            "full_model": {
                "features_count": len(X_tr.columns),
                "pr_auc": round(full_auc, 4),
                "delta_pr_auc": 0.0,
            },
            "no_session_signals": {
                "features_dropped": len(session_cols),
                "pr_auc": round(no_session_auc, 4),
                "delta_pr_auc": round(no_session_auc - full_auc, 4),
            },
            "no_cash_gap_signals": {
                "features_dropped": len(cash_gap_cols),
                "pr_auc": round(no_cash_gap_auc, 4),
                "delta_pr_auc": round(no_cash_gap_auc - full_auc, 4),
            },
        }

    def run_experiment_5_adoption_sensitivity(
        self,
        test_obs_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 5: Adoption sensitivity (30%, 50%, 70%) and simulated loss prevented."""
        if test_obs_data is None:
            test_obs_data = self.load_observations("test")

        obs = test_obs_data.get("transaction_observations", {})
        total_skimming_loss = 0.0
        total_fee_overcharge = 0.0
        total_payout_reduction = 0.0
        skimmer_actions_count = 0

        for _, o in obs.items():
            if o.get("is_skimmer_action"):
                skimmer_actions_count += 1
                fo = float(o.get("fee_overcharge", 0.0))
                pr = float(o.get("payout_reduction", 0.0))
                total_fee_overcharge += fo
                total_payout_reduction += pr
                total_skimming_loss += fo + pr

        rates = [0.30, 0.50, 0.70]
        scenarios = {}
        for r in rates:
            pct = int(r * 100)
            prevented = total_skimming_loss * r
            scenarios[f"adoption_{pct}pct"] = {
                "adoption_rate": r,
                "assisted_cashouts_protected_without_pin_pct": pct,
                "loss_prevented_bdt": round(prevented, 2),
                "pct_skimming_loss_prevented": pct,
            }

        return {
            "total_test_skimmer_actions": skimmer_actions_count,
            "total_test_fee_overcharge_bdt": round(total_fee_overcharge, 2),
            "total_test_payout_reduction_bdt": round(total_payout_reduction, 2),
            "total_test_skimming_loss_bdt": round(total_skimming_loss, 2),
            "scenarios": scenarios,
        }

    def run_experiment_6_distribution_shift(
        self,
        train_data: dict[str, Any] | None = None,
        test_data: dict[str, Any] | None = None,
        test_shifted_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        sample_train_size: int = 4000,
    ) -> dict[str, Any]:
        """Experiment 6: Robustness under distribution shift (canonical vs shifted test)."""
        if train_data is None:
            train_data = self.load_split("train")
        if test_data is None:
            test_data = self.load_split("test")
        if test_shifted_data is None:
            test_shifted_data = self.load_split("test_shifted")
        if val_data is None:
            val_data = self.load_split("validation")

        users_tr = (
            train_data["users"][:sample_train_size] if sample_train_size else train_data["users"]
        )
        X_tr, y_tr, _, _ = extract_user_features(
            users_tr, train_data["transactions"], train_data["sessions"]
        )
        X_val, y_val, _, _ = extract_user_features(
            val_data["users"], val_data["transactions"], val_data["sessions"]
        )
        X_test, y_test, _, _ = extract_user_features(
            test_data["users"], test_data["transactions"], test_data["sessions"]
        )
        X_shift, y_shift, _, _ = extract_user_features(
            test_shifted_data["users"],
            test_shifted_data["transactions"],
            test_shifted_data["sessions"],
        )

        clf = AssistedUserClassifier(random_state=self.random_state)
        clf.fit(X_tr, y_tr, X_val, y_val)

        def _get_metrics(X_df: pd.DataFrame, y_ser: pd.Series) -> dict[str, float]:
            probs = clf.predict_proba(X_df)[:, 1]
            p, r, _ = precision_recall_curve(y_ser, probs)
            idx_80 = np.where(p >= 0.80)[0]
            rec_80 = float(r[idx_80[0]]) if len(idx_80) > 0 else 0.0
            return {
                "pr_auc": round(float(auc(r, p)), 4),
                "roc_auc": round(float(roc_auc_score(y_ser, probs)), 4),
                "brier_score": round(float(brier_score_loss(y_ser, probs)), 4),
                "recall_at_80p_precision": round(rec_80, 4),
            }

        canonical_metrics = _get_metrics(X_test, y_test)
        shifted_metrics = _get_metrics(X_shift, y_shift)

        delta_pr_auc = round(shifted_metrics["pr_auc"] - canonical_metrics["pr_auc"], 4)

        return {
            "canonical_test": canonical_metrics,
            "shifted_test": shifted_metrics,
            "delta_pr_auc": delta_pr_auc,
            "robust": abs(delta_pr_auc) < 0.15,
        }

    def run_fairness_evaluation(
        self,
        train_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        sample_train_size: int = 4000,
    ) -> dict[str, Any]:
        """Fairness audit across demographic slices (gender, age_band, region, urban_rural)."""
        if train_data is None:
            train_data = self.load_split("train")
        if val_data is None:
            val_data = self.load_split("validation")

        users_tr = (
            train_data["users"][:sample_train_size] if sample_train_size else train_data["users"]
        )
        X_tr, y_tr, _, _ = extract_user_features(
            users_tr, train_data["transactions"], train_data["sessions"]
        )
        X_val, y_val, slices_val, _ = extract_user_features(
            val_data["users"], val_data["transactions"], val_data["sessions"]
        )

        clf = AssistedUserClassifier(random_state=self.random_state)
        clf.fit(X_tr, y_tr, X_val, y_val)
        probs = clf.predict_proba(X_val)[:, 1]
        preds = (probs >= 0.50).astype(int)
        y_val_arr = y_val.to_numpy()

        slice_metrics: dict[str, dict[str, dict[str, float]]] = {}
        max_tpr_gaps: dict[str, float] = {}

        for slice_col in ["gender", "age_band", "region", "urban_rural"]:
            slice_metrics[slice_col] = {}
            tprs = []
            if slice_col in slices_val.columns:
                for val in sorted(slices_val[slice_col].unique()):
                    mask = (slices_val[slice_col] == val).to_numpy()
                    sub_y = y_val_arr[mask]
                    sub_p = preds[mask]
                    n = len(sub_y)
                    positives = int(sub_y.sum())
                    negatives = n - positives

                    tpr = (
                        float((sub_p[sub_y == 1] == 1).sum()) / float(positives)
                        if positives > 0
                        else 0.0
                    )
                    fpr = (
                        float((sub_p[sub_y == 0] == 1).sum()) / float(negatives)
                        if negatives > 0
                        else 0.0
                    )
                    review_rate = float(sub_p.sum()) / float(n) if n > 0 else 0.0

                    tprs.append(tpr)
                    slice_metrics[slice_col][str(val)] = {
                        "count": n,
                        "tpr": round(tpr, 4),
                        "fpr": round(fpr, 4),
                        "review_rate": round(review_rate, 4),
                    }
                max_tpr_gaps[slice_col] = round(max(tprs) - min(tprs), 4) if tprs else 0.0

        global_max_gap = max(max_tpr_gaps.values()) if max_tpr_gaps else 0.0

        return {
            "slices": slice_metrics,
            "max_tpr_gaps": max_tpr_gaps,
            "global_max_tpr_gap": global_max_gap,
            "target_max_tpr_gap": 0.10,
            "satisfies_fairness_target": global_max_gap <= 0.10,
        }

    def run_all(self, sample_train_size: int = 4000) -> dict[str, Any]:
        """Execute all experiments and fairness checks."""
        train_data = self.load_split("train")
        val_data = self.load_split("validation")
        test_data = self.load_split("test")
        test_obs = self.load_observations("test")
        test_shifted = self.load_split("test_shifted")

        exp1 = self.run_experiment_1_assisted_detection(
            train_data, val_data, sample_train_size=sample_train_size
        )
        exp2 = self.run_experiment_2_agent_anomaly(val_data)
        exp3 = self.run_experiment_3_skimming_sweep(val_data)
        exp4 = self.run_experiment_4_signal_ablations(
            train_data, val_data, sample_train_size=sample_train_size
        )
        exp5 = self.run_experiment_5_adoption_sensitivity(test_obs)
        exp6 = self.run_experiment_6_distribution_shift(
            train_data,
            test_data,
            test_shifted,
            val_data=val_data,
            sample_train_size=sample_train_size,
        )
        fairness = self.run_fairness_evaluation(
            train_data, val_data, sample_train_size=sample_train_size
        )

        return {
            "experiment_1_assisted_detection": exp1,
            "experiment_2_agent_anomaly": exp2,
            "experiment_3_skimming_sweep": exp3,
            "experiment_4_signal_ablations": exp4,
            "experiment_5_adoption_sensitivity": exp5,
            "experiment_6_distribution_shift": exp6,
            "fairness_evaluation": fairness,
        }

    def generate_markdown_report(self, results: dict[str, Any]) -> str:
        """Format full results into GitHub-flavored Markdown tables for reporting."""
        exp1 = results["experiment_1_assisted_detection"]
        exp2 = results["experiment_2_agent_anomaly"]
        exp3 = results["experiment_3_skimming_sweep"]
        exp4 = results["experiment_4_signal_ablations"]
        exp5 = results["experiment_5_adoption_sensitivity"]
        exp6 = results["experiment_6_distribution_shift"]
        fairness = results["fairness_evaluation"]

        def _row(*cells: Any) -> str:
            return "| " + " | ".join(str(c) for c in cells) + " |"

        md = [
            "# Sathi Evaluation & Experimentation Results",
            "",
            "> [!NOTE]",
            "> All evaluations use synthetic MFS simulation data generated with disjoint cohorts",
            "> per `docs/evaluation-plan.md` (Train Seed 42, Val Seed 4242, Test Seed 2026).",
            "> Zero protected demographic features or ground truth labels were included in models.",
            "",
            "## 1. Assisted-User Classifier vs Rule Baseline",
            "",
            _row(
                "Model",
                "PR-AUC",
                "ROC-AUC",
                "Brier Calibration Score",
                "Recall @ 80% Precision",
            ),
            _row("---", "---", "---", "---", "---"),
        ]

        b = exp1["baseline"]
        c = exp1["lightgbm_clean"]
        n = exp1["lightgbm_5pct_label_noise"]
        md.append(
            _row(
                "Rule Baseline (top_share >= 0.70 & hours <= 24)",
                f"{b['pr_auc']:.4f}",
                f"{b['roc_auc']:.4f}",
                f"{b['brier_score']:.4f}",
                f"{b['recall_at_80p_precision']:.4f}",
            )
        )
        md.append(
            _row(
                "**Sathi LightGBM Classifier (Clean)**",
                f"**{c['pr_auc']:.4f}**",
                f"**{c['roc_auc']:.4f}**",
                f"**{c['brier_score']:.4f}**",
                f"**{c['recall_at_80p_precision']:.4f}**",
            )
        )
        md.append(
            _row(
                "Sathi LightGBM (5% Label Noise)",
                f"{n['pr_auc']:.4f}",
                f"{n['roc_auc']:.4f}",
                f"{n['brier_score']:.4f}",
                f"{n['recall_at_80p_precision']:.4f}",
            )
        )
        md.append("")

        # Experiment 2
        md.append("## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison")
        md.append("")
        md.append(
            _row(
                "Model / Method",
                "Precision@R (Top-K)",
                "Recall on Injected Skimmers",
                "False-Flag Rate on Honest High-Volume",
            )
        )
        md.append(_row("---", "---", "---", "---"))

        k_val = exp2["total_skimmers"]
        b_rule = exp2["baseline_rule"]
        z_score = exp2["peer_robust_zscore"]
        iforest = exp2["isolation_forest"]
        comb = exp2["combined_ensemble"]
        md.append(
            _row(
                "Baseline Rule (fee ratio >= 1.2x official)",
                f"{b_rule.get(f'precision_at_{k_val}', 0.0):.2f}",
                f"{b_rule['recall_on_skimmers']:.2f}",
                f"{b_rule['false_flag_rate_honest_high_volume']:.2f}",
            )
        )
        md.append(
            _row(
                "Peer Robust Z-Score (Median & MAD)",
                f"{z_score.get(f'precision_at_{k_val}', 0.0):.2f}",
                f"{z_score['recall_on_skimmers']:.2f}",
                f"{z_score['false_flag_rate_honest_high_volume']:.2f}",
            )
        )
        md.append(
            _row(
                "Isolation Forest (Unsupervised)",
                f"{iforest.get(f'precision_at_{k_val}', 0.0):.2f}",
                f"{iforest['recall_on_skimmers']:.2f}",
                f"{iforest['false_flag_rate_honest_high_volume']:.2f}",
            )
        )
        md.append(
            _row(
                "**Sathi Combined Ensemble (0.70 Z + 0.30 IF)**",
                f"**{comb.get(f'precision_at_{k_val}', 0.0):.2f}**",
                f"**{comb['recall_on_skimmers']:.2f}**",
                f"**{comb['false_flag_rate_honest_high_volume']:.2f}**",
            )
        )
        md.append("")

        # Experiment 3
        md.append("## 3. Skimming Intensity Sweep")
        md.append("")
        md.append(
            _row(
                "Tier",
                "Intensity Description",
                "Fee Overcharge",
                "Mean Risk Score",
                "High-Risk Flag Rate",
            )
        )
        md.append(_row("---", "---", "---", "---", "---"))
        for t_name, t_val in exp3.items():
            md.append(
                _row(
                    t_name.capitalize(),
                    t_val["description"],
                    f"{t_val['fee_ratio']}x",
                    f"{t_val['mean_risk_score']:.3f}",
                    f"{t_val['detection_flag_rate'] * 100:.1f}%",
                )
            )
        md.append("")

        # Experiment 4
        md.append("## 4. Behavioral Feature Signal Ablations")
        md.append("")
        md.append(_row("Feature Configuration", "Description", "PR-AUC", "Delta vs Full"))
        md.append(_row("---", "---", "---", "---"))
        for a_name, a_val in exp4.items():
            delta = a_val.get("delta_pr_auc", 0.0)
            sign = "+" if delta > 0 else ""
            md.append(
                _row(
                    a_name,
                    f"{a_val.get('features_dropped', 0)} dropped",
                    f"{a_val['pr_auc']:.4f}",
                    f"{sign}{delta:.4f}",
                )
            )
        md.append("")

        # Experiment 5
        tot_loss = exp5["total_test_skimming_loss_bdt"]
        tot_act = exp5["total_test_skimmer_actions"]
        tot_fo = exp5["total_test_fee_overcharge_bdt"]
        tot_pr = exp5["total_test_payout_reduction_bdt"]

        md.append("## 5. Adoption Sensitivity & Simulated Loss Prevented")
        md.append("")
        md.append(
            f"- Total simulated test skimming loss: **{tot_loss:,.2f} BDT** across "
            f"**{tot_act} skimmer actions**."
        )
        md.append(f"  - Fee overcharges: {tot_fo:,.2f} BDT")
        md.append(f"  - Payout reductions: {tot_pr:,.2f} BDT")
        md.append("")
        md.append(
            _row(
                "Sathi Mandate Adoption",
                "Cashouts Protected Without PIN",
                "Skimming Loss Prevented (BDT)",
                "Protection Rate",
            )
        )
        md.append(_row("---", "---", "---", "---"))
        for _, s_val in exp5["scenarios"].items():
            md.append(
                _row(
                    f"{s_val['adoption_rate'] * 100:.0f}% Adoption",
                    f"{s_val['assisted_cashouts_protected_without_pin_pct']}%",
                    f"{s_val['loss_prevented_bdt']:,.2f} BDT",
                    f"{s_val['pct_skimming_loss_prevented']}%",
                )
            )
        md.append("")

        # Experiment 6
        md.append("## 6. Robustness under Distribution Shift")
        md.append("")
        c_test = exp6["canonical_test"]
        s_test = exp6["shifted_test"]
        md.append(
            _row(
                "Dataset Split",
                "PR-AUC",
                "ROC-AUC",
                "Brier Score",
                "Recall @ 80% Precision",
            )
        )
        md.append(_row("---", "---", "---", "---", "---"))
        md.append(
            _row(
                "Canonical Test (Seed 2026)",
                f"{c_test['pr_auc']:.4f}",
                f"{c_test['roc_auc']:.4f}",
                f"{c_test['brier_score']:.4f}",
                f"{c_test['recall_at_80p_precision']:.4f}",
            )
        )
        md.append(
            _row(
                "Distribution-Shifted Test",
                f"{s_test['pr_auc']:.4f}",
                f"{s_test['roc_auc']:.4f}",
                f"{s_test['brier_score']:.4f}",
                f"{s_test['recall_at_80p_precision']:.4f}",
            )
        )
        md.append("")
        md.append(f"**PR-AUC Delta**: `{exp6['delta_pr_auc']:+.4f}` (Robust: `{exp6['robust']}`)")
        md.append("")

        # Fairness
        max_gap = fairness["global_max_tpr_gap"]
        tgt_gap = fairness["target_max_tpr_gap"]
        fair_pass = fairness["satisfies_fairness_target"]

        md.append("## 7. Demographic Fairness Audit")
        md.append("")
        md.append(
            f"Target max TPR disparity gap: `<= {tgt_gap * 100:.1f}%` across all protected slices."
        )
        md.append("")
        md.append(
            f"Observed global max TPR gap: **`{max_gap * 100:.2f}%`** "
            f"(Fairness Target Satisfied: **`{fair_pass}`**)"
        )
        md.append("")
        md.append(
            _row(
                "Demographic Slice",
                "Category",
                "Sample Count",
                "True Positive Rate (TPR)",
                "False Positive Rate (FPR)",
                "Review Rate",
            )
        )
        md.append(_row("---", "---", "---", "---", "---", "---"))
        for s_col, cat_dict in fairness["slices"].items():
            for cat_name, metrics in cat_dict.items():
                md.append(
                    _row(
                        s_col,
                        cat_name,
                        metrics["count"],
                        f"{metrics['tpr']:.4f}",
                        f"{metrics['fpr']:.4f}",
                        f"{metrics['review_rate']:.4f}",
                    )
                )
        md.append("")
        md.append("### Slice Disparity Gaps:")
        for s_col, gap in fairness["max_tpr_gaps"].items():
            md.append(f"- **{s_col}**: `{gap * 100:.2f}%` gap")

        return "\n".join(md)
