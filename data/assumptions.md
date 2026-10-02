# Synthetic Data Assumptions

All data is synthetic. Nothing here is real upay data. Every value below is an assumption to be validated with governed real data in any pilot. Change values in `data/config.yaml`, then record the change here.

## 1. Population
| Item | Value | Note |
|---|---|---|
| Simulation start timestamp | 2026-10-01T00:00:00Z | ASSUMPTION: synthetic timeline anchor; not official T+0 |
| Customers | 20,000 | Four groups below |
| Agents | 300 | Normal, high-volume honest, skimmers |
| Window | 90 days | Daily granularity |
| Random seeds | train=42, validation=4242, test=2026 | Different seeds and disjoint agents for each split |

| Customer group | Share | Behavior |
|---|---|---|
| Independent urban | 40% | Mixed services, varied agents, low retry rate |
| Independent rural | 25% | More cash-out, moderate agent concentration |
| Assisted: allowance recipients | 20% | Fixed disbursement cycle, cash-out soon after credit, high agent concentration |
| Assisted: family-helped | 15% | Helper-initiated, evening spikes, moderate concentration |

## 2. Signals and Approved Simulation Distributions
All distributions are nested in `data/config.yaml` rather than hardcoded in the generator.

| Signal | Independent | Assisted | Details / Approved Distribution |
|---|---|---|---|
| Share of cash-outs at top agent | Urban: Beta(2, 5)<br>Rural: Beta(3, 4) | Beta(6, 2) | Deliberate overlap: 15% loyal independent users adopt assisted Beta(6, 2) |
| Hours from credit to cash-out | Exponential(mean=72h) | Exponential(mean=8h) | Assisted cash out rapidly after credit |
| Fraction of balance withdrawn | Beta(2, 3) | Beta(8, 2) | Assisted withdraw near-full balance |
| PIN retry rate | Poisson(lambda=0.1) | Poisson(lambda=0.5) | Assisted experience more retries |
| PIN entry duration | Lognormal(median=6s, sigma=0.45) | Lognormal(median=14s, sigma=0.75) | Assisted median 14s with larger variance |
| Services used (count) | 1 + Poisson(lambda=3.0) | 1 + Poisson(lambda=0.7) | Independent use diverse services |
| Session steps | 4 steps | 7 steps | Assisted navigation requires more steps |
| Initial balance | 5,000 BDT | 5,000 BDT | Auxiliary default |
| Minimum cash-out | 100 BDT | 100 BDT | Auxiliary default |

### Credit cycles
- **Allowance recipients**: Fixed disbursement on day 5 of a 30-day cycle, amount range 1,500–5,000 BDT.
- **Family-helped**: Irregular credits, daily probability 0.08, amount range 1,500–5,000 BDT.
- **Independent users**: 30-day credit cycle, amount range 1,500–5,000 BDT.
- **Extra services**: Probability 0.15 per cycle, amount range 100–500 BDT.

## 3. Label Noise and Overlap (Required)
- 10% label noise (`label_noise: 0.10`): 10% of assisted labels flipped to independent-like behavior and vice versa.
- Feature distributions overlap so classification is not trivially separable.
- Independent loyal fraction: 15% of independent users adopt the assisted top-share distribution Beta(6, 2).
- Report results with and without noise.

## 4. Agent Behavior
| Type | Count | Assisted Share | Fee Rate / Multiplier | Volume / Notes |
|---|---|---|---|---|
| Normal | ~270 | 0.20 | Official rate (1.5%, mult=1.0) | Random amounts, no payout reduction |
| High-volume honest | ~20 | 0.20 | Official rate (1.5%, mult=1.0) | 3x customer weight, 2x allowance-day volume; measures false positives |
| Skimmers | ~10 | 0.60 | Elevated per intensity | Target assisted users; elevated fees and rounded/reduced payouts |

### Skimming intensity profiles
Configured intensity is `moderate` (default). Evaluate on all three:
- **Subtle**: Fee multiplier 1.1 on 10% of transactions; rare payout reduction on 2% of transactions with 1%–3% reduction.
- **Moderate** (*selected*): Fee multiplier 1.25 on 30% of transactions; payout reduction on 20% of transactions with 3%–5% reduction.
- **Obvious**: Fee multiplier 1.5 on 60% of transactions; payout reduction on 40% of transactions with 5%–10% reduction.

## 5. Key Limitation: Skimming is Mostly Invisible in the Ledger
If an agent hands over less cash than the ledger records, the ledger shows the full amount. Detection relies on indirect signals (fee ratio, round-down patterns, concentration, complaints) and on the **cash-received confirmation** the verification flow collects.
- Customers report cash received with probability `customer_report_rate: 0.6`.
- Customer report accuracy: `customer_report_accuracy: 0.9`.
- Customer report noise: Gaussian noise with sigma `auxiliary_assumptions.customer_report_noise_sigma_bdt: 50` BDT.

## 6. Fee, Caps and Policy Limits (Approved Assumptions)
All figures below are human-approved simulation ASSUMPTIONS, NEVER real upay figures:
- **Official cash-out fee rate**: 0.015 (1.5%) (`official_fee_rate: 0.015` in config).
- **Per-user mandate cap**: 5,000 BDT default (`user_cap_default: 5000` in config).
- **Daily cash-out limit**: 25,000 BDT (`daily_cash_out_limit: 25000` in config).
- **Mandate TTL**: 15 minutes (`mandate_ttl_minutes: 15` in config).
- **Max verification attempts**: 2 attempts (`max_verification_attempts: 2` in config; note: this does NOT define wrong-code lockout).
- **Cash gap tolerance**: `max(50, 0.02 * amount)` BDT (`cash_gap: {min_bdt: 50, rate: 0.02}`).

## 7. Auxiliary Implementation Assumptions (Reproducibility Defaults)
Where the human approved general behavior without complete parameterization, the following auxiliary defaults are chosen by the implementation team for deterministic generator reproducibility. **No claim is made that the human specified these auxiliary parameters**:
- **PIN entry lognormal sigma**: Independent sigma = 0.45; Assisted sigma = 0.75 (capturing larger assisted variance).
- **Independent loyal fraction**: 0.15 of independent users draw from the assisted top-agent share distribution Beta(6, 2).
- **Subtle skimmer payout reduction**: Probability 0.02 on cash-outs, reduction amount 1%–3% (0.01–0.03).
- **Customer report noise sigma**: 50 BDT Gaussian noise on reported amounts.
- **Disbursement cycle duration**: 30 days for allowance recipients and independent users.
- **Family credit daily probability**: 0.08 per day with amount range 1,500–5,000 BDT.
- **Independent credit amount range**: 1,500–5,000 BDT per 30-day cycle.
- **Initial balance**: 5,000 BDT.
- **Minimum cash-out**: 100 BDT.
- **Extra service probability**: 0.15 per 30-day cycle, amount range 100–500 BDT.
- **Session steps**: Independent = 4 steps; Assisted = 7 steps.

## 8. Splits and Evaluation Boundaries
- Train/validation/test split **by agent and by seed**, not by row.
- Agent allocation: 60% train, 20% validation, 20% test (human-approved); seeds 42 / 4242 / 2026.
- Exact agent cohort counts (300 total): 180 train, 60 validation, 60 test.
- Stratified agent types across cohorts: normal 162/54/54, high-volume honest 12/4/4, skimmers 6/2/2.
- Customer split across cohorts (20,000 total): 12,000 train, 4,000 validation, 4,000 test.
- Agents belong to exactly one cohort. Each user's entire timeline (all transactions and sessions) routes strictly within their home cohort agents. Metadata / evaluation reports are linked only within the same cohort.
- A clean test set is never used for training or threshold tuning; generating the test artifact only is not evaluating it.
- **Immutable seed provenance**: Changing simulation configuration requires a fresh dev dataset database/schema or new seed namespaces; no reseed overwrite or reset command exists to prevent test set contamination.
- Baseline vs model heldout agents and second seed remain future modeling, do not train now.

## 9. Model Sanity Check Ceiling
- **Max PR-AUC sanity threshold**: 0.98 (`models.sanity.max_pr_auc: 0.98`).
- Diagnostic purpose: Future validation-only diagnosis. If validation PR-AUC exceeds 0.98, report widening feature overlap.
- Never tune the generator to improve the score or inspect the final test set to tune models.

## 10. Fairness and Synthetic Evaluation Slices
Evaluation slices exist for fairness evaluation only, never as model inputs:
- `gender`: `[female, male, other]`
- `age_band`: `["18-25", "26-40", "41-60", "60+"]`
- `region`: `[dhaka, chittagong, rajshahi, khulna, barishal, sylhet, rangpur, mymensingh]`
- `urban_rural`: `[urban, rural]`
- Max TPR gap target: 0.10.

## 11. Adoption Scenarios for Impact Simulation
Sathi adoption among assisted users: 30%, 50%, 70%. Report all three.

## 12. Ethics
- No real names, numbers, NID values or photos. IDs are deterministic synthetic tokens; no real identifiers are used.
- Gender, age band and region exist for fairness evaluation only, never as model inputs.

## 13. Change Log
| Date | Change | Reason |
|---|---|---|
| 2026-10-02 | Added validation seed 4242 and 60/20/20 agent allocation | Human approved explicit validation setup; fee and caps remain unset pending separate values |
| 2026-10-02 | Approved Phase 1 simulation assumptions and auxiliary defaults | Human approved fee (0.015), mandate cap (5000 BDT), daily limit (25000 BDT), TTL (15 min), verification attempts (2), cash gap max(50,.02*amt), population/agent distributions, skimming profiles and report rate/accuracy. Noise magnitude is an auxiliary implementation assumption. Added distinct auxiliary implementation assumptions for generator reproducibility and 0.98 PR-AUC sanity ceiling. |
| 2026-10-02 | Implemented T015 disjoint agent and seed split tooling | Disjoint agent allocation (180/60/60) stratified across agent types (normal 162/54/54, high 12/4/4, skimmers 6/2/2) and customer splits (12k/4k/4k) across seeds 42/4242/2026. Documented immutable seed provenance, loader validation, and manifest tracking. |

## Generator implementation details (ASSUMPTIONS)

- Ledger amounts/credits use a configured 50 BDT rounding increment; affordability and payouts retain cents precision. Payout reduction percentages are rounded to cents, not coarse denominations that would exaggerate skimming.
- Opening balances are synthetic add-money credits at 5–60 minutes from the timeline anchor. Credit hour windows: allowance7–12, family8–20, independent8–12; extra services9–21. These auxiliary windows are configurable, not observed customer facts.
- Agent assisted shares0.2/0.6 are relative sampling propensities. With35% global assisted population they cannot guarantee each agent's exact assisted fraction. Sidecars record realized fractions.
- High-volume honest allowance-day multiplier acts on requested amount and is capped by available balance including fee. Realized aggregate volume need not equal exactly2x; it is not forced to match a target.
- Service-count draws drive activity-use opportunities, not the number of distinct service categories: the current schema offers credit/cash_out/send/bill_pay. Additional service types remain outside Phase1.
- Actual payouts, noisy reports, effective profiles and sampled propensities live in a simulation sidecar, not the ledger seed tables. No model may consume latent simulation truth. The cash-report sidecar has no applicable domain storage table until mandate reporting is implemented.

| Date | Change | Reason |
|---|---|---|
| 2026-10-02 | Added configurable rounding/time windows and clarified agent propensities, volume cap and service-count proxy | Auxiliary generator ASSUMPTIONS; preserve balances and existing schema without tuning to a model score |

Extra-service active cycle-day range1–28 is a configurable auxiliary ASSUMPTION, clamped to short cycles. Cycle days are zero-based offsets from the synthetic timeline anchor.

Sidecar assisted-fraction summaries count transactions using effective behavior profiles; they are not exact assisted-customer share guarantees and must not be quoted as customer demographics.
