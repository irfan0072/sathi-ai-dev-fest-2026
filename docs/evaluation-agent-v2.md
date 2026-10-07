# Extended agent benchmark v2 (synthetic)

> **Status: synthetic evidence.** Same generator, features and detectors as the canonical experiment, on a much larger independently seeded population. It does **not** modify the canonical benchmark (`docs/evaluation-results.md`, `data/generated/`, `data/artifacts/`). It says nothing about real skimming prevalence, real customer reporting or real loss.

- Version `agent-benchmark-v2.0` · protocol sha256 `6b8ccda470b3f560…` · dev results sha256 `614f4ac99dd80e94…`
- Git revision `156477f9b2a7` · worktree had uncommitted changes: True · completed 2026-10-07T03:56:42.684502+00:00
- Reproduce: `python scripts/agent_benchmark_v2.py --phase dev` then `--phase final` (one shot), verify with `--phase verify`. Archive: `data/benchmarks/agent_v2/`.

## Design (fixed in `protocol.json` before any data was generated)

- **3 independent replications**, each with its own registry seed (1101, 2201, 3301); canonical seeds [42, 4242, 2026] are not reused. Every replication has 3000 new simulated agents split into disjoint train (40%), validation (20%) and final (40%) cohorts. Pooled counts below are independent agents; repeated scenarios on the same agents are robustness checks, not new agents.
- **Prevalence and behaviour preserved** from `data/config.yaml` (90% normal, 6.67% honest high-volume, 3.33% skimmers; customers per agent unchanged; documented `moderate` profile). Nothing in the simulator was tuned to make a score attractive.
- **Development vs final.** The detector is fitted on train. Validation cohorts were used for development (one candidate change, below). The final cohorts (new seeds, never generated before the final phase) were scored **once** with the frozen detector, the fixed 0.8 high-risk threshold from the config and predeclared review budgets. No threshold was tuned.
- **Two policies, two denominators.** *Threshold policy*: flag agents with risk >= 0.8; recall and precision over flagged agents. *Review-budget policy*: rank agents and look at the top K (K = 15 as in the canonical run, or 5%, 10%, 25% of the cohort); precision at K and recall at K. They answer different questions and must not be mixed.
- Intervals are 95% Wilson intervals on pooled independent-agent counts. Precision at K intervals are approximate (selections inside one cohort are not independent); per-replication values are shown to expose seed variation.

## Final cohorts: denominators

Moderate scenario, pooled over 3 replications: **3600 agents, 120 skimmers, 3480 honest agents, 240 honest high-volume agents**. The canonical held-out cohort had 60 agents, 2 skimmers and 4 honest high-volume agents.

## Headline: documented moderate skimming (final cohorts)

| Method | Recall at threshold | Precision at threshold | Flagged | Honest false flags | Honest high-volume false flags |
|---|---|---|---:|---|---|
| Rule baseline (fee ratio >= 1.2) | 0/120 = 0.0% [0.00-0.03] | n/a (0 flagged) | 0 | 0/3480 = 0.0% [0.00-0.00] | 0/240 = 0.0% [0.00-0.02] |
| Peer robust z-score | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 120 | 0/3480 = 0.0% [0.00-0.00] | 0/240 = 0.0% [0.00-0.02] |
| Isolation forest | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 120 | 0/3480 = 0.0% [0.00-0.00] | 0/240 = 0.0% [0.00-0.02] |
| Deployed ensemble (0.7 z + 0.3 iForest) | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 120 | 0/3480 = 0.0% [0.00-0.00] | 0/240 = 0.0% [0.00-0.02] |
| Candidate: ensemble + support-aware shortfall (dev-selected, not deployed) | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 120 | 0/3480 = 0.0% [0.00-0.00] | 0/240 = 0.0% [0.00-0.02] |

Review-budget policy (moderate, final):

| Method | P@15 | P@5% | P@10% | P@25% | Skimmers found at 5% (of all) |
|---|---|---|---|---|---|
| Rule baseline (fee ratio >= 1.2) | 45/45 = 100.0% [0.92-1.00] | 120/180 = 66.7% [0.59-0.73] | 120/360 = 33.3% [0.29-0.38] | 120/900 = 13.3% [0.11-0.16] | 120/120 = 100.0% [0.97-1.00] |
| Peer robust z-score | 45/45 = 100.0% [0.92-1.00] | 120/180 = 66.7% [0.59-0.73] | 120/360 = 33.3% [0.29-0.38] | 120/900 = 13.3% [0.11-0.16] | 120/120 = 100.0% [0.97-1.00] |
| Isolation forest | 45/45 = 100.0% [0.92-1.00] | 120/180 = 66.7% [0.59-0.73] | 120/360 = 33.3% [0.29-0.38] | 120/900 = 13.3% [0.11-0.16] | 120/120 = 100.0% [0.97-1.00] |
| Deployed ensemble (0.7 z + 0.3 iForest) | 45/45 = 100.0% [0.92-1.00] | 120/180 = 66.7% [0.59-0.73] | 120/360 = 33.3% [0.29-0.38] | 120/900 = 13.3% [0.11-0.16] | 120/120 = 100.0% [0.97-1.00] |
| Candidate: ensemble + support-aware shortfall (dev-selected, not deployed) | 45/45 = 100.0% [0.92-1.00] | 120/180 = 66.7% [0.59-0.73] | 120/360 = 33.3% [0.29-0.38] | 120/900 = 13.3% [0.11-0.16] | 120/120 = 100.0% [0.97-1.00] |

## All scenarios (final cohorts): recall at the fixed threshold

| Scenario | Skimmers | Rule baseline | Deployed ensemble | Candidate | Honest high-volume false flags (deployed) |
|---|---:|---|---|---|---|
| `moderate` | 120 | 0/120 = 0.0% [0.00-0.03] | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 0/240 = 0.0% [0.00-0.02] |
| `noisy_reports` | 120 | 0/120 = 0.0% [0.00-0.03] | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 0/240 = 0.0% [0.00-0.02] |
| `obvious` | 120 | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 0/240 = 0.0% [0.00-0.02] |
| `sparse_reports` | 120 | 0/120 = 0.0% [0.00-0.03] | 120/120 = 100.0% [0.97-1.00] | 120/120 = 100.0% [0.97-1.00] | 0/240 = 0.0% [0.00-0.02] |
| `subtle` | 120 | 0/120 = 0.0% [0.00-0.03] | 0/120 = 0.0% [0.00-0.03] | 0/120 = 0.0% [0.00-0.03] | 0/240 = 0.0% [0.00-0.02] |
| `unchanged_fee_shortfall_moderate` | 120 | 0/120 = 0.0% [0.00-0.03] | 0/120 = 0.0% [0.00-0.03] | 119/120 = 99.2% [0.95-1.00] | 0/240 = 0.0% [0.00-0.02] |
| `unchanged_fee_shortfall_subtle` | 120 | 0/120 = 0.0% [0.00-0.03] | 0/120 = 0.0% [0.00-0.03] | 0/120 = 0.0% [0.00-0.03] | 0/240 = 0.0% [0.00-0.02] |

## All scenarios (final cohorts): ranking at a review budget of 5% of agents

| Scenario | Rule baseline P@5% | Deployed ensemble P@5% | Candidate P@5% | Deployed AP (mean of replications) |
|---|---|---|---|---:|
| `moderate` | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 1.0 |
| `noisy_reports` | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 1.0 |
| `obvious` | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 1.0 |
| `sparse_reports` | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 1.0 |
| `subtle` | 120/180 = 66.7% [0.59-0.73] | 91/180 = 50.6% [0.43-0.58] | 90/180 = 50.0% [0.43-0.57] | 0.7065 |
| `unchanged_fee_shortfall_moderate` | 1/180 = 0.6% [0.00-0.03] | 120/180 = 66.7% [0.59-0.73] | 120/180 = 66.7% [0.59-0.73] | 0.9837 |
| `unchanged_fee_shortfall_subtle` | 3/180 = 1.7% [0.01-0.05] | 34/180 = 18.9% [0.14-0.25] | 34/180 = 18.9% [0.14-0.25] | 0.185 |

## The one development-only candidate

`ensemble_v2_shortfall` = max(deployed ensemble risk, support-aware repeated-shortfall risk). The shortfall risk is the Wilson lower bound of an agent's customer-reported cash-shortfall rate minus the train-population median rate, and it needs shortfall reports from at least 2 distinct customers and at least 5 reports. It uses ledger payouts and customer reports only (no actual-cash or label columns). It was **not** added to the deployed model bundle.

Selection rule (predeclared, evaluated on validation only): {"evaluated_on": "validation cohorts, pooled over replications; never on final cohorts", "honest_hv_false_flag_increase_max_pp": 1.0, "honest_hv_false_flag_increase_max_pp_on": "moderate", "precision_at_5pct_not_lower_on": "moderate", "recall_gain_min_pp": 5.0, "recall_gain_min_pp_on": "unchanged_fee_shortfall_moderate"}.
Validation result: {"false_flag_ok": true, "honest_hv_false_flag_increase_pp": 0, "precision_at_5pct_v1": 0.6667, "precision_at_5pct_v2": 0.6667, "precision_ok": true, "recall_gain_ok": true, "recall_gain_pp": 100.0} → **candidate selected: True**.

## What the numbers do and do not show

- **Moderate skimming (documented profile):** the deployed ensemble flags every skimmer and no honest agent in this simulator, and the rule baseline (fee ratio >= 1.2) flags none, because an agent's *average* fee ratio stays well below 1.2. The perfect separation also says the simulated task is easy: honest agents here charge exactly the official fee (zero fee noise), so any overcharge stands out. Real fee noise, rounding and promotions are absent. Zero false flags among 240 honest high-volume agents bounds the true rate only to roughly 1.6% at 95% confidence (Wilson upper bound).
- **Subtle skimming is still not flagged at the fixed 0.8 threshold:** the deployed ensemble flags 0 of 120 subtle skimmers (the best single method, the isolation forest, flags 1). Ranking tells a different story only because of the zero-noise assumption: ordering agents by fee ratio alone (peer z-score, or the rule score) puts every subtle skimmer at the top (average precision 1.0), while the deployed ensemble ranks them worse (average precision about 0.71) because the isolation-forest component adds noise. Do not read the ranking numbers as field detection.
- **Unchanged-fee cash shortfalls** (correct ledger fee, short payout) are invisible to the deployed ensemble at the threshold (0 of 120 moderate shortfalls flagged) because its peer component scores fees. The development-only candidate flags 119 of 120 of them with no honest false flags. Subtle shortfalls (rare 1-3% payout reductions) remain essentially undetected by every method (0 of 120 flagged, average precision about 0.18). The candidate is benchmark-side only and is not in the deployed model bundle.
- **Review-budget ceilings:** each final cohort has 40 skimmers in 1,200 agents, so precision at a 5% budget (60 slots) cannot exceed 40/60 = 66.7% and at 10% (120 slots) cannot exceed 33.3%. Values at those numbers are at the ceiling, not weak. P@15 is capped at 100%.
- **Sparse (20% of customers report) and noisy (70% accurate) reports** did not change the deployed ensemble's recall here, because in this simulator the fee component carries the moderate-skimming signal. They would matter for shortfall-only behaviour, which this table does not combine with sparse reports.
- **Compute and code:** dev took about 3 minutes per replication; the final phase about 20 minutes per replication on a memory-constrained laptop. After the final phase the only edit to `agent_benchmark.py` was an import-block reformat for the linter (as-run sha256 `b744be4a…`, now `aa186161…`); results do not depend on it.
- All results are synthetic. Pending (external): real agent and customer data under a governed pilot, real reporting behaviour, honest-agent noise, and a supported intervention.

## Per-replication spread (final, moderate, deployed ensemble)

| Replication | Skimmers | Recall | Honest high-volume flagged |
|---:|---:|---:|---:|
| 1 | 40 | 40/40 | 0/80 |
| 2 | 40 | 40/40 | 0/80 |
| 3 | 40 | 40/40 | 0/80 |

## Limits

- Synthetic data from the project's own simulator; customer reports follow its noise model. No real prevalence, reporting behaviour or loss is implied.
- Scenario rows on the same agents are robustness checks, not additional independent agents; the independent-agent counts are per replication cohort.
- Precision at a review budget and threshold precision/recall are different policies with different denominators and must not be mixed.
