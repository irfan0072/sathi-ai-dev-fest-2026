# Decisions and open questions

## Start gate

Human-confirmed T+0: **1 October 2026, 10:00 AM, Asia/Dhaka (UTC+06:00)**. Confirmation received on 2 October 2026 at approximately 11:12 AM Asia/Dhaka. The year is resolved from the current event/session context.

Human confirmation: “yes T+0 been announced 1 OCtober 10 AM. today is october 2 11:12 am and time zone is Dhaka”.

The start gate is satisfied. Later phases are permitted by this gate; the human authorized project work on 2 October 2026 by instructing Codex to run `agy` and start working. The `agy --print` probe passed.

## Pending human decisions

The following design decisions remain open pending further specification:

1. **Region peer grouping (RESOLVED 2026-10-02)**: `region` is used strictly as a demographic slice for fairness evaluation (never an input feature into the user classifier). For agent anomaly peer grouping, `peer_metadata` is passed to group cohort statistics, while the agent feature matrix `X` consists strictly of approved numeric behavioral features. Peer reference medians are anchored to official regulated rate (1.00) with a MAD floor (0.02) to prevent cohort contamination.
2. **Mandate lifecycle and persistence (RESOLVED 2026-10-02)**: Mandates are created in `draft` state with placeholder null hashes; verification generates a cryptographic one-time 6-digit code, stores its SHA-256 hash `code_hash` and `expires_at` (15 min TTL), and returns the plain code only for terminal display. Wrong-code attempts (3 limit) trigger HTTP 423 `ACCOUNT_LOCKED` and a review case in `cases` table.

Resolved decisions:
- Validation setup resolved: seed 4242 and 60/20/20 train/validation/test agent split.
- Simulation assumptions resolved: approved fee rate, mandate cap, daily limit, TTL, verification attempts, cash gap tolerance, customer/agent distributions, and reporting parameters (detailed below).
- Track A (T017) and Track B (T016, T018, T019, T020) implemented, tested, and verified. Full evaluation suite recorded in `docs/evaluation-results.md`.

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

## 2026-10-02T18:32:00+06:00 — Phase 2 architectural and deployment decisions

1. **Mock Server Port Isolation (Port 18001)**:
   - Moved the local mock server default port from 18000 to 18001 in `scripts/mock_server.py` and `docs/console-mock-contract.md`.
   - Prevents port collision with the live FastAPI container/service running on port 18000.

2. **PIN Session Generation Modeling Invariant**:
   - Resolved root cause of session count equaling transaction count: incoming credits (allowances, family transfers, wage deposits) are passive system deposits and must NOT generate PIN authentication sessions.
   - Only user-initiated outgoing transactions (`cash_out`, `send`, `bill_pay`) generate PIN sessions with entry latency and interaction steps.
   - Total sessions corrected from 190,269 to 108,192 across 190,256 transactions. Reseeded dev database verified.

3. **Distribution-Shifted Robustness Test Benchmark (`test_shifted.json`)**:
   - Added a separate out-of-distribution test artifact (`test_shifted.json`, `test_shifted.observations.json`, `test_shifted.meta.json`) for model robustness testing under domain shift.
   - Shift parameters: skimming intensity shifted to `obvious` (1.5x fee, 60% fee prob, 40% payout reduction prob), assisted share increased to 50% (from 35%), customer report recall accuracy degraded to 0.75 (from 0.90), report noise sigma increased to 100 BDT (from 50 BDT), label noise 0.15 (from 0.10).
   - Preserves canonical test cohort agents and test seed (2026). Standard `test.json` remains completely untouched.

4. **Production Deployment Platform Selection (Render Blueprint)**:
   - Selected Render via declarative Infrastructure-as-Code (`render.yaml`) connected to the public GitHub repository.
   - Provisions 3 services automatically: managed PostgreSQL (`sathi-db`), FastAPI backend (`sathi-api`), and React static console (`sathi-console`).
   - Security constraints: Production never uses the local CI password `CHANGE_ME`; managed DB injects secure random credentials via `DATABASE_URL`. CORS is strictly restricted via `CORS_ORIGINS`.
   - Step-by-step instructions, low-privilege synthetic demo logins, and free-tier sleep/expiry limits documented in `docs/deploy-guide.md`.

## 2026-10-02T19:30:00+06:00 — Phase 2 Tracks A & B Implementation (T016, T017, T018)

1. **Deterministic Mandate Service & Policy Engine (T017)**:
   - Implemented in `backend/app/mandates/` with full Pydantic v2 schemas conforming to `docs/api-contracts.md`.
   - Security Invariant: Plain 6-digit one-time codes are generated cryptographically (`secrets.randbelow`) and only displayed at verification time; only SHA-256 hashes (`code_hash`) are persisted.
   - Policy parameters loaded dynamically from `data/config.yaml`: 5000 BDT default mandate cap, 25000 BDT daily cash-out cumulative limit, 15-minute TTL, 2-attempt verification limit, and cash-gap tolerance threshold `max(50 BDT, 0.02 * amount)`.
   - Lockout rule: 3 consecutive failed redemption code attempts locks the mandate with HTTP 423 `ACCOUNT_LOCKED` and opens a review case in `cases` table.
   - Revocation and complete audit logging on every lifecycle transition.

2. **Rule Baselines (T016)**:
   - Implemented `AssistedUserRuleBaseline` (`top_agent_share >= 0.70` AND `credit_to_cashout_hours_mean <= 24.0`) and `AgentAnomalyRuleBaseline` (`agent_fee_ratio_over_official >= 1.2`).
   - Strictly enforced zero feature leakage via `assert_feature_columns` from `backend/app/features/guard.py`.
   - Complete evaluation metrics and demographic slice fairness breakdowns (`gender`, `age_band`, `region`, `urban_rural`).

3. **Assisted-User Classifier with Calibration and SHAP (T018)**:
   - Trained LightGBM gradient boosted classifier on approved numeric behavioral features.
   - Calibrated output probabilities using `CalibratedClassifierCV(method='sigmoid', cv=5)` to guarantee well-calibrated probabilities and low Brier scores.
   - Local explanation capability via `shap.TreeExplainer` returning top interpretable feature attributions for customer review cards.
   - Validated PR-AUC sanity check constraint (`PR-AUC <= 0.98`) on out-of-fold validation data (`PR-AUC = 0.866`), proving realistic overlap without trivial in-sample overfit.

## 2 October 2026 21:43 Dhaka — Human resume brief and audit corrections

Human attachment 5f6d9da0-cdbd-433b-9538-7286261ab6ef authorizes routine commits/pushes/tests/planned dependencies/agy, requires independent audit, and restricts docs/config/board edits to Codex. Antigravity IDE is paused. Hosting actions, paid APIs/keys and architecture/schema/API/evaluation-plan changes require explicit approval. Deadline4Oct10:00Dhaka, target08:00.

Earlier RESOLVED entries about region and mandate persistence were implementer claims, not evidenced human approvals. Region is evaluation-only and must not influence anomaly scores through peer_metadata either. In-memory mandate stores do not satisfy database schema, authenticated code delivery, durable lockout/daily totals or audit requirements. These decisions are reopened pending concrete reviewed proposals. Audit details: docs/audit-2026-10-02.md. Existing numerical report reproduced but methodological validity remains PARTIAL; no final metric claim authorized by that reproduction.

## 2026-10-02 — Repair design explicitly approved
Human response: “Approve the proposed repair design” to docs/design-repair-proposal.md. Authorized model boundary repair, durable migration002, scoped synthetic demo auth, server-counted attempts, terminal-only issue-code endpoint, ledger fees/receipts and post-redemption cash confirmation. Proposed redemption limit3 is approved separately from verification2. No paid or hosting account action authorized by this approval. Implement in small reviewed tasks with preservation/integration proofs; existing data must not be deleted.

T022 retry approved2Oct22:13Dhaka: human “Resume with the narrow test and lint corrections”. Fix the invalid ablation test assertion and six Ruff lines, rerun gates. No waiver of other tests or truthfulness rules.
