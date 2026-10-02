# Decisions and open questions

## Start gate

Human-confirmed T+0: **1 October 2026, 10:00 AM, Asia/Dhaka (UTC+06:00)**. Confirmation received on 2 October 2026 at approximately 11:12 AM Asia/Dhaka. The year is resolved from the current event/session context.

Human confirmation: “yes T+0 been announced 1 OCtober 10 AM. today is october 2 11:12 am and time zone is Dhaka”.

The start gate is satisfied. Later phases are permitted by this gate; the human authorized project work on 2 October 2026 by instructing Codex to run `agy` and start working. The `agy --print` probe passed.

## Pending human decisions

The following design decisions remain open pending further specification:

1. **Region peer grouping**: Resolve evaluation-only region versus region-based agent peer groups. `region` is an evaluation slice in the fairness specification, while the agent anomaly model design references peer groups `[region, volume_band]`.
2. **Mandate lifecycle and persistence**: Clarify requested mandate `code_hash` and `expires_at` storage timing (schema requires non-null columns at creation, whereas code generation follows verification), authenticated agent terminal code delivery mechanism, wrong-code lockout persistence and threshold, and daily-limit tracking. Note: approved verification attempts (2) does not define wrong-code lockout.

Resolved decisions:
- Validation setup resolved: seed 4242 and 60/20/20 train/validation/test agent split.
- Simulation assumptions resolved: approved fee rate, mandate cap, daily limit, TTL, verification attempts, cash gap tolerance, customer/agent distributions, and reporting parameters (detailed below).

## Resolved implementer selection

The human supplied the `agy` alias and authorized project work. `/Users/apple/.local/bin/agy` is available; read-only print mode and interactive implementation were verified. See `agent-workflow.md` for command permissions and invocation details.

## 2026-10-02T11:53:35+06:00 — GitHub remote authorized

The human supplied https://github.com/irfan0072/sathi-ai-dev-fest-2026.git and explicitly instructed Codex to use it and continue work. Remote inspection returned no refs. Local existing history is preserved on main; no history reset or force push is authorized or used. Regular pushes to this remote are authorized.

## Phase 1 scenario responses

- Fee/cap proposal was not adopted initially: human chose to keep settings unset and will supply different simulation values.
- Official fee rate, mandate cap and daily limit remained null in config until human approval on 2026-10-02.
- Human approved validation seed 4242 and disjoint 60/20/20 train/validation/test agent allocation. Existing train/test seeds 42 and 2026 remain. Config, assumptions and evaluation plan updated accordingly.
- Human responses recorded before config/evaluation-plan edits. No fee/cap values were assumed.

Confirmation recorded at 2026-10-02T12:19:00+06:00: “Keep these unset; I’ll provide different simulation values” and “Use seed 4242 and a 60/20/20 agent split”.

## 2026-10-02T13:10:37+06:00 — Approved local ports

Human: “Resume with API 18000 and frontend 13000”. T006 resumed using those localhost bindings; internal container ports stay 8000/80 and the existing PHP service remains running.

## 2026-10-02T14:43:31+06:00 — Public runtime deployment deferred

Human response to hosting-account question: “for now work in local”. Continue local work; public runtime deployment is deferred. The previously authorized GitHub remote and regular source pushes remain in use.

## 2026-10-02 — Approved Phase 1 simulation assumptions (T012)

Human approved Phase 1 simulation assumptions on 2026-10-02. All values are explicitly simulation ASSUMPTIONS, NEVER real upay figures.

### 1. Approved Policy & Fee Values
- Official fee rate: `0.015` (1.5%) (`official_fee_rate: 0.015`).
- Default mandate cap: `5000` BDT (`user_cap_default: 5000`).
- Daily cash-out limit: `25000` BDT (`daily_cash_out_limit: 25000`).
- Mandate TTL: `15` minutes (`mandate_ttl_minutes: 15`).
- Max verification attempts: `2` (`max_verification_attempts: 2`; does not define wrong-code lockout).
- Cash gap tolerance: `max(50, 0.02 * amount)` BDT (`cash_gap: {min_bdt: 50, rate: 0.02}`).

### 2. Approved Population & Behavioral Distributions
- Top agent share: Independent urban Beta(2, 5); Independent rural Beta(3, 4); Assisted Beta(6, 2).
- Credit-to-cashout delay: Independent Exponential(mean=72h); Assisted Exponential(mean=8h).
- Withdrawn balance fraction: Independent Beta(2, 3); Assisted Beta(8, 2).
- PIN retries: Independent Poisson(0.1); Assisted Poisson(0.5).
- PIN entry duration: Independent Lognormal(median=6s, sigma=0.45); Assisted Lognormal(median=14s, sigma=0.75).
- Service count: Independent 1 + Poisson(3.0); Assisted 1 + Poisson(0.7).
- Allowance credit cycle: Day 5 of cycle, range 1,500–5,000 BDT.
- Family credits: Irregular, daily probability 0.08, range 1,500–5,000 BDT.
- Noise and overlap: Label noise 0.10; deliberate overlap with 15% loyal independent users using assisted top-share Beta(6, 2).

### 3. Approved Agent Behavior & Skimming Profiles
- Normal agents (~270): Assisted share 0.20, official fee rate (multiplier 1.0).
- High-volume honest agents (~20): 3x customer weight, 2x allowance-day volume, official fee rate.
- Skimmers (~10): Assisted share 0.60.
- Skimming intensities (moderate selected):
  - Subtle: Fee multiplier 1.1 on 10% of transactions; rare payout reduction on 2% of transactions with 1%–3% reduction.
  - Moderate: Fee multiplier 1.25 on 30% of transactions; payout reduction on 20% of transactions with 3%–5% reduction.
  - Obvious: Fee multiplier 1.5 on 60% of transactions; payout reduction on 40% of transactions with 5%–10% reduction.
- Customer reporting: Probability 0.60, accuracy 0.90, noise sigma 50 BDT.

### 4. Auxiliary Implementation Defaults for Reproducibility
The following auxiliary assumptions are recorded distinctly as implementation choices for deterministic reproducibility where user specification was incomplete (no claim is made that human specified them):
- PIN lognormal sigma: 0.45 (independent) / 0.75 (assisted).
- Independent loyal fraction: 0.15 adopting assisted top-share Beta(6, 2).
- Subtle payout reduction: 0.02 probability with 0.01–0.03 reduction.
- Report noise sigma: 50 BDT.
- Credit cycle: 30 days for allowance recipients and independent users.
- Family credit daily probability: 0.08, amount range 1,500–5,000 BDT.
- Independent credit cycle: 30 days, amount range 1,500–5,000 BDT.
- Initial balance: 5,000 BDT.
- Minimum cashout: 100 BDT.
- Amount rounding increment: 50 BDT (`amount_rounding_bdt: 50`).
- Extra-service probability: 0.15 per cycle, amount range 100–500 BDT.
- Session steps: Independent 4, Assisted 7.

### 5. Fixed Start Timestamp, Slices & Sanity Ceiling
- Simulation start timestamp: Fixed `2026-10-01T00:00:00Z` (UTC).
- Evaluation slice categories: Defined in config (`gender`, `age_band`, `region`, `urban_rural`).
- Model sanity check: Max PR-AUC 0.98. Validation-only diagnosis to check feature overlap; generator must never be tuned to score or inspect final test set.
- Modeling boundaries: Baseline vs model heldout agents and second seed remain future modeling, do not train now.

## 2026-10-02T18:01:37+06:00 — Orchestrator handover

Orchestrator changed from Codex to Antigravity at 2026-10-02T18:01:37+06:00 (12:01:37 UTC); Codex reached its usage limit. Antigravity assumes lead engineer and orchestrator roles for Sathi.
