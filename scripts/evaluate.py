#!/usr/bin/env python3
"""CLI script to run Sathi evaluation experiments and fairness audits.

Outputs structured results and saves docs/evaluation-results.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend package is in python path
repo_root = Path(__file__).resolve().parent.parent
backend_path = repo_root / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.evaluation.suite import EvaluationRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sathi evaluation suite")
    parser.add_argument(
        "--splits-dir",
        type=str,
        default=None,
        help="Path to data/generated/splits directory",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default="docs/evaluation-results.md",
        help="File path to save the generated markdown report",
    )
    parser.add_argument(
        "--sample-train-size",
        type=int,
        default=4000,
        help="Number of training users to sample for fast evaluation (default 4000)",
    )
    args = parser.parse_args()

    print("==================================================")
    print("Sathi Evaluation Suite (AI DEV FEST 2026 - upay)")
    print("==================================================")

    runner = EvaluationRunner(splits_dir=args.splits_dir)
    print(f"Splits directory: {runner.splits_dir}")
    print(
        f"Sampling {args.sample_train_size} training users for calibration & training..."
    )

    results = runner.run_all(sample_train_size=args.sample_train_size)

    report_md = runner.generate_markdown_report(results)

    out_path = repo_root / args.output_report
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")
    print(f"\n[SUCCESS] Generated markdown report saved to: {out_path}")

    # Print summary highlights
    exp1 = results["experiment_1_assisted_detection"]
    exp2 = results["experiment_2_agent_anomaly"]
    exp5 = results["experiment_5_adoption_sensitivity"]
    fairness = results["fairness_evaluation"]

    comb_m = exp2["combined_ensemble"]
    s50 = exp5["scenarios"]["adoption_50pct"]

    print("\n--- Key Headline Results ---")
    print(
        f"Assisted User Classifier PR-AUC: {exp1['lightgbm_clean']['pr_auc']:.4f} "
        f"(Rule Baseline: {exp1['baseline']['pr_auc']:.4f})"
    )
    print(
        f"Agent Anomaly Combined Recall on Skimmers: {comb_m['recall_on_skimmers'] * 100:.1f}% "
        f"(Honest HV False-Flag: {comb_m['false_flag_rate_honest_high_volume'] * 100:.1f}%)"
    )
    print(
        f"Simulated Loss Prevented @ 50% Adoption: {s50['loss_prevented_bdt']:,.2f} BDT "
        f"({s50['pct_skimming_loss_prevented']}% of eligible loss)"
    )
    print(
        f"Fairness Global Max TPR Gap: {fairness['global_max_tpr_gap'] * 100:.2f}% "
        f"(Target: <= {fairness['target_max_tpr_gap'] * 100:.1f}%, "
        f"Pass: {fairness['satisfies_fairness_target']})"
    )
    print("==================================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
