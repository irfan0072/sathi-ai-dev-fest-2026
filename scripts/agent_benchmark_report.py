#!/usr/bin/env python3
# ruff: noqa: E501  (generates markdown tables; line length is not meaningful here)
"""Render docs/evaluation-agent-v2.md from the archived benchmark results (no recomputation).

    python scripts/agent_benchmark_report.py [--in data/benchmarks/agent_v2] [--out docs/evaluation-agent-v2.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))

METHODS = ["rule_baseline", "peer_robust_zscore", "isolation_forest", "ensemble_v1",
           "ensemble_v2_shortfall"]
LABEL = {"rule_baseline": "Rule baseline (fee ratio >= 1.2)", "peer_robust_zscore": "Peer robust z-score",
         "isolation_forest": "Isolation forest", "ensemble_v1": "Deployed ensemble (0.7 z + 0.3 iForest)",
         "ensemble_v2_shortfall": "Candidate: ensemble + support-aware shortfall (dev-selected, not deployed)"}


def rate(r: dict | None) -> str:
    if not r or not r.get("denominator"):
        return "n/a (0 flagged)" if r else "n/a"
    ci = r.get("ci95")
    ci_text = f" [{ci[0]:.2f}-{ci[1]:.2f}]" if ci else ""
    return f"{r['numerator']}/{r['denominator']} = {r['rate']:.1%}{ci_text}"


def render(final: dict, dev: dict, protocol: dict) -> str:
    pooled = final["pooled"]
    mod = pooled["moderate"]["ensemble_v1"]["denominators"]
    reps = final["replications"]
    lines = [
        "# Extended agent benchmark v2 (synthetic)",
        "",
        "> **Status: synthetic evidence.** Same generator, features and detectors as the canonical "
        "experiment, on a much larger independently seeded population. It does **not** modify the "
        "canonical benchmark (`docs/evaluation-results.md`, `data/generated/`, `data/artifacts/`). "
        "It says nothing about real skimming prevalence, real customer reporting or real loss.",
        "",
        f"- Version `{final['benchmark_version']}` · protocol sha256 `{protocol['protocol_sha256'][:16]}…` "
        f"· dev results sha256 `{final['dev_results_sha256'][:16]}…`",
        f"- Git revision `{final['provenance']['git_revision'][:12]}` · worktree had uncommitted "
        f"changes: {final['provenance']['worktree_has_uncommitted_changes']} · completed {final['completed_at']}",
        "- Reproduce: `python scripts/agent_benchmark_v2.py --phase dev` then `--phase final` "
        "(one shot), verify with `--phase verify`. Archive: `data/benchmarks/agent_v2/`.",
        "",
        "## Design (fixed in `protocol.json` before any data was generated)",
        "",
        f"- **3 independent replications**, each with its own registry seed "
        f"({', '.join(str(r['seed_train']) for r in protocol['replications'])}); canonical seeds "
        f"{protocol['canonical_seeds_not_reused']} are not reused. Every replication has "
        f"{protocol['agents_per_replication']} new simulated agents split into disjoint train (40%), "
        f"validation (20%) and final (40%) cohorts. Pooled counts below are independent agents; "
        f"repeated scenarios on the same agents are robustness checks, not new agents.",
        "- **Prevalence and behaviour preserved** from `data/config.yaml` (90% normal, 6.67% honest "
        "high-volume, 3.33% skimmers; customers per agent unchanged; documented `moderate` profile). "
        "Nothing in the simulator was tuned to make a score attractive.",
        "- **Development vs final.** The detector is fitted on train. Validation cohorts were used for "
        "development (one candidate change, below). The final cohorts (new seeds, never generated "
        "before the final phase) were scored **once** with the frozen detector, the fixed 0.8 "
        "high-risk threshold from the config and predeclared review budgets. No threshold was tuned.",
        "- **Two policies, two denominators.** *Threshold policy*: flag agents with risk >= 0.8; "
        "recall and precision over flagged agents. *Review-budget policy*: rank agents and look at the "
        "top K (K = 15 as in the canonical run, or 5%, 10%, 25% of the cohort); precision at K and "
        "recall at K. They answer different questions and must not be mixed.",
        "- Intervals are 95% Wilson intervals on pooled independent-agent counts. Precision at K "
        "intervals are approximate (selections inside one cohort are not independent); per-replication "
        "values are shown to expose seed variation.",
        "",
        "## Final cohorts: denominators",
        "",
        f"Moderate scenario, pooled over {len(reps)} replications: **{mod['agents']} agents, "
        f"{mod['skimmers']} skimmers, {mod['honest_agents']} honest agents, "
        f"{mod['honest_high_volume']} honest high-volume agents**. The canonical held-out cohort had "
        "60 agents, 2 skimmers and 4 honest high-volume agents.",
        "",
        "## Headline: documented moderate skimming (final cohorts)",
        "",
        "| Method | Recall at threshold | Precision at threshold | Flagged | Honest false flags | Honest high-volume false flags |",
        "|---|---|---|---:|---|---|",
    ]
    for m in METHODS:
        e = pooled["moderate"][m]
        t = e["threshold_policy"]
        lines.append(f"| {LABEL[m]} | {rate(t['recall_on_skimmers'])} | {rate(t['precision'])} | "
                     f"{t['flagged_total']} | {rate(t['false_flags_total_honest'])} | "
                     f"{rate(t['false_flags_honest_high_volume'])} |")
    lines += ["", "Review-budget policy (moderate, final):", "",
              "| Method | P@15 | P@5% | P@10% | P@25% | Skimmers found at 5% (of all) |",
              "|---|---|---|---|---|---|"]
    for m in METHODS:
        b = pooled["moderate"][m]["review_budget_policy"]
        lines.append(f"| {LABEL[m]} | {rate(b['absolute_15']['precision_at_budget'])} | "
                     f"{rate(b['pct_5']['precision_at_budget'])} | {rate(b['pct_10']['precision_at_budget'])} | "
                     f"{rate(b['pct_25']['precision_at_budget'])} | {rate(b['pct_5']['recall_at_budget'])} |")
    lines += [
        "",
        "## All scenarios (final cohorts): recall at the fixed threshold",
        "",
        "| Scenario | Skimmers | Rule baseline | Deployed ensemble | Candidate | Honest high-volume false flags (deployed) |",
        "|---|---:|---|---|---|---|",
    ]
    for name, entry in pooled.items():
        rule = entry["rule_baseline"]["threshold_policy"]["recall_on_skimmers"]
        v1 = entry["ensemble_v1"]["threshold_policy"]
        v2 = entry["ensemble_v2_shortfall"]["threshold_policy"]["recall_on_skimmers"]
        lines.append(f"| `{name}` | {entry['ensemble_v1']['denominators']['skimmers']} | {rate(rule)} | "
                     f"{rate(v1['recall_on_skimmers'])} | {rate(v2)} | "
                     f"{rate(v1['false_flags_honest_high_volume'])} |")
    lines += [
        "",
        "## All scenarios (final cohorts): ranking at a review budget of 5% of agents",
        "",
        "| Scenario | Rule baseline P@5% | Deployed ensemble P@5% | Candidate P@5% | Deployed AP (mean of replications) |",
        "|---|---|---|---|---:|",
    ]
    for name, entry in pooled.items():
        row = [rate(entry[m]["review_budget_policy"]["pct_5"]["precision_at_budget"])
               for m in ("rule_baseline", "ensemble_v1", "ensemble_v2_shortfall")]
        lines.append(f"| `{name}` | {row[0]} | {row[1]} | {row[2]} | "
                     f"{entry['ensemble_v1']['average_precision_mean']} |")
    d = dev["decision"]
    lines += [
        "",
        "## The one development-only candidate",
        "",
        "`ensemble_v2_shortfall` = max(deployed ensemble risk, support-aware repeated-shortfall risk). "
        "The shortfall risk is the Wilson lower bound of an agent's customer-reported cash-shortfall "
        "rate minus the train-population median rate, and it needs shortfall reports from at least 2 "
        "distinct customers and at least 5 reports. It uses ledger payouts and customer reports only "
        "(no actual-cash or label columns). It was **not** added to the deployed model bundle.",
        "",
        f"Selection rule (predeclared, evaluated on validation only): {json.dumps(d['selection_rule'])}.",
        f"Validation result: {json.dumps(d['checks'])} → **candidate selected: "
        f"{d['candidate_selected']}**.",
        "",
        "## What the numbers do and do not show",
        "",
        "- **Moderate skimming (documented profile):** the deployed ensemble flags every skimmer and "
        "no honest agent in this simulator, and the rule baseline (fee ratio >= 1.2) flags none, "
        "because an agent's *average* fee ratio stays well below 1.2. The perfect separation also "
        "says the simulated task is easy: honest agents here charge exactly the official fee (zero "
        "fee noise), so any overcharge stands out. Real fee noise, rounding and promotions are absent. "
        "Zero false flags among 240 honest high-volume agents bounds the true rate only to roughly "
        "1.6% at 95% confidence (Wilson upper bound).",
        "- **Subtle skimming is still not flagged at the fixed 0.8 threshold:** the deployed ensemble "
        "flags 0 of 120 subtle skimmers (the best single method, the isolation forest, flags 1). "
        "Ranking tells a different story only because of the zero-noise assumption: ordering agents "
        "by fee ratio alone (peer z-score, or the rule score) puts every subtle skimmer at the top "
        "(average precision 1.0), while the deployed ensemble ranks them worse (average precision "
        "about 0.71) because the isolation-forest component adds noise. Do not read the ranking "
        "numbers as field detection.",
        "- **Unchanged-fee cash shortfalls** (correct ledger fee, short payout) are invisible to the "
        "deployed ensemble at the threshold (0 of 120 moderate shortfalls flagged) because its peer "
        "component scores fees. The development-only candidate flags 119 of 120 of them with no "
        "honest false flags. Subtle shortfalls (rare 1-3% payout reductions) remain essentially "
        "undetected by every method (0 of 120 flagged, average precision about 0.18). The candidate is "
        "benchmark-side only and is not in the deployed model bundle.",
        "- **Review-budget ceilings:** each final cohort has 40 skimmers in 1,200 agents, so precision "
        "at a 5% budget (60 slots) cannot exceed 40/60 = 66.7% and at 10% (120 slots) cannot exceed "
        "33.3%. Values at those numbers are at the ceiling, not weak. P@15 is capped at 100%.",
        "- **Sparse (20% of customers report) and noisy (70% accurate) reports** did not change the "
        "deployed ensemble's recall here, because in this simulator the fee component carries "
        "the moderate-skimming signal. They would matter for shortfall-only behaviour, which this "
        "table does not combine with sparse reports.",
        "- **Compute and code:** dev took about 3 minutes per replication; the final phase about 20 "
        "minutes per replication on a memory-constrained laptop. After the final phase the only edit "
        "to `agent_benchmark.py` was an import-block reformat for the linter (as-run sha256 "
        "`b744be4a…`, now `aa186161…`); results do not depend on it.",
        "- All results are synthetic. Pending (external): real agent and customer data under a "
        "governed pilot, real reporting behaviour, honest-agent noise, and a supported intervention.",
        "",
        "## Per-replication spread (final, moderate, deployed ensemble)",
        "",
        "| Replication | Skimmers | Recall | Honest high-volume flagged |",
        "|---:|---:|---:|---:|",
    ]
    for r in reps:
        e = r["scenarios"]["moderate"]["ensemble_v1"]
        lines.append(f"| {r['replication']} | {e['skimmers']} | "
                     f"{e['flagged_skimmers']}/{e['skimmers']} | "
                     f"{e['flagged_honest_high_volume']}/{e['honest_high_volume']} |")
    lines += ["", "## Limits", "", *[f"- {item}" for item in final["limits"]]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default="data/benchmarks/agent_v2")
    parser.add_argument("--out", default="docs/evaluation-agent-v2.md")
    args = parser.parse_args(argv)
    src = Path(args.src)
    final = json.loads((src / "final_results.json").read_text())
    dev = json.loads((src / "dev_results.json").read_text())
    protocol = json.loads((src / "protocol.json").read_text())
    Path(args.out).write_text(render(final, dev, protocol), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
