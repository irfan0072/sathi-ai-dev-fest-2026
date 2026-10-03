#!/usr/bin/env python3
"""CLI script to run Sathi evaluation experiments and fairness audits.

Outputs structured results, models, and artifacts to data/generated/evaluation.
Writes to documentation paths only when explicitly requested via --output-report.
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

from app.evaluation.artifacts import (  # noqa: E402
    ArtifactUnavailableError,
    ArtifactVerificationError,
    SanityCeilingExceededError,
)
from app.evaluation.suite import EvaluationRunner  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for evaluation runner."""
    parser = argparse.ArgumentParser(
        prog="python scripts/evaluate.py",
        description="Run Sathi reproducible evaluation suite and generate artifacts",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="data/config.yaml",
        help="Path to YAML configuration file (defaults to data/config.yaml)",
    )
    parser.add_argument(
        "--splits-dir",
        type=str,
        default="data/generated/splits",
        help="Path to data/generated/splits directory (defaults to data/generated/splits)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/generated/evaluation",
        help="Directory to save evaluation artifacts and results",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default=None,
        help="Optional documentation path to write the markdown report (Codex owns docs)",
    )
    parser.add_argument(
        "--sample-train-size",
        type=int,
        default=4000,
        help="Training sample size (deterministic seed, default 4000, 0 for all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute evaluation suite, save artifacts, and report results."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Cleanly reject negative sampling
    if args.sample_train_size < 0:
        print("Error: --sample-train-size cannot be negative.", file=sys.stderr)
        return 1

    print("==================================================")
    print("Sathi Evaluation Suite (AI DEV FEST 2026 - upay)")
    print("==================================================")

    sample_size = args.sample_train_size if args.sample_train_size > 0 else None

    try:
        runner = EvaluationRunner(
            splits_dir=args.splits_dir,
            config_path=args.config,
        )
        print(f"Splits directory: {runner.splits_dir}")
        print(f"Configuration: {args.config}")
        if sample_size is not None:
            print(f"Deterministic training sample size: {sample_size} users")
        else:
            print("Using full training set")

        results = runner.run_all(sample_train_size=sample_size)

        out_path = Path(args.output_dir)
        runner.save_evaluation_run(output_dir=out_path, results=results)
        print(f"\n[SUCCESS] Evaluation run artifacts successfully saved to: {out_path}")
        print(f"  - Results JSON: {out_path / 'results.json'}")
        print(f"  - Markdown Report: {out_path / 'generated-report.md'}")
        print(f"  - Assisted Model: {out_path / 'assisted.joblib'}")
        print(f"  - Agent Model: {out_path / 'agent.joblib'}")
        print(f"  - Run Manifest: {out_path / 'manifest.json'}")
        print(f"  - Deployment Bundle: {out_path / 'deployment'}")

        if args.output_report:
            report_md = runner.generate_markdown_report(results)
            doc_path = Path(args.output_report)
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(report_md, encoding="utf-8")
            print(f"  - Documentation report saved to: {doc_path}")

        # Print summary highlights
        exp1 = results["experiment_1_assisted_detection"]
        exp2 = results["experiment_2_agent_anomaly"]
        exp5 = results["experiment_5_adoption_sensitivity"]
        fairness = results["fairness_evaluation"]

        comb_m = exp2["combined_ensemble"]
        s50 = exp5["scenarios"]["adoption_50pct"]
        t_held = exp1["held_out_test"]["assisted_classifier"]
        b_held = exp1["held_out_test"]["rule_baseline"]

        print("\n--- Key Headline Results ---")
        print(
            f"Assisted User Classifier PR-AUC (Held-out): {t_held['pr_auc']:.4f} "
            f"(Rule Baseline: {b_held['pr_auc']:.4f})"
        )
        ff_str = (
            f" (Honest HV False-Flag: {comb_m['false_flag_rate_honest_high_volume'] * 100:.1f}%)"
            if comb_m.get("false_flag_rate_honest_high_volume") is not None
            else ""
        )
        print(
            f"Agent Anomaly Combined Recall on Skimmers: "
            f"{comb_m['recall_on_skimmers'] * 100:.1f}%{ff_str}"
        )
        print(
            f"Simulated Loss Prevented @ 50% Adoption: {s50['loss_prevented_bdt']:,.2f} BDT "
            f"({s50['pct_eligible_assisted_loss_prevented']}% of eligible loss)"
        )
        global_gap = fairness["global_max_tpr_gap"]
        gap_str = f"{global_gap * 100:.2f}%" if global_gap is not None else "N/A"
        print(
            f"Fairness Global Max TPR Gap: {gap_str} "
            f"(Target: <= {fairness['target_max_tpr_gap'] * 100:.1f}%, "
            f"Pass: {fairness['satisfies_fairness_target']})"
        )
        print("==================================================")
        return 0

    except (
        ArtifactUnavailableError,
        ArtifactVerificationError,
        SanityCeilingExceededError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"\n[ERROR] Evaluation execution halted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
