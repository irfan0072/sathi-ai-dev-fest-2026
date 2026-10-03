# Sathi — submission report draft

Status: engineering draft, 3 October 2026. Synthetic simulation only. Final evaluation and public deployment remain pending; the durable local API demo is verified; this draft must be completed before submission. No real upay customer data, rates or transactions are used.

## Summary

Sathi explores a cash-out flow in which a customer confirms an amount and an agent receives a scoped, expiring, one-time code. Behavioral models suggest outreach and agent review; deterministic policy governs the mandate. A synthetic simulation lets us compare rules and models without collecting customer PINs or personal financial data.

Verified repair checkpoint T024:307 backend tests with zero skips,17 frontend tests, lint/build and rebuilt Docker API pass. The actual local API flow exercised scoped login, amount confirmation, one-time agent code, redemption, replay rejection, cash reporting, receipt and persisted review/lockout state across restart. All preexisting simulation rows and migration001 were preserved. The console's authenticated flow is still pending T025. Engineering checks do not establish fraud reduction or real-world accuracy. Final held-out results remain pending.

## Problem and proposed idea

Consider an illustrative customer who needs assistance using a financial service. Sharing a reusable PIN gives the helper more authority than a single cash-out needs. Sathi proposes limiting that authority by amount, agent and time, while preserving an independent customer amount-confirmation step. The example is fictional.

A qualitative study published21August2025 examined68 interviews with older adults and widows in Kurigram and described assistance needs and PIN sharing when accessing mobile allowances. This supports investigating assisted use; it does not establish national prevalence or validate Sathi's simulation percentages. [Shitol et al., Experiences of older adults and widows with government allowance programmes](https://onlinelibrary.wiley.com/doi/10.1111/ijsw.70033).

## Implemented solution and remaining repairs

The project contains a configurable synthetic generator, agent/seed-based splits, rule baselines, LightGBM and anomaly model code, a React console and a FastAPI service. The local console now distinguishes illustrative samples from verified outputs and shows unavailable metrics when evaluation artifacts are missing.

Verified local API capabilities include durable PostgreSQL mandate state, server-side attempts, scoped synthetic authentication, terminal-only code issuance, exact ledger fees and actual receipts. A3,000BDT synthetic redemption debited3,045BDT with an assumed45BDT fee. Public deployment has not been verified.

## AI approach

Simulation assumptions are in data/config.yaml and data/assumptions.md. Independent and assisted behaviors deliberately overlap, including10% label noise and independently loyal customers. Normal agents, honest high-volume agents and subtle/moderate/obvious injected skimmers support comparisons and false-flag measurement.

User signals come from observed transaction/session behavior. T023 verified train-only LightGBM fitting, frozen-estimator calibration on separate validation agents, and SHAP additivity on that same base model in raw log-odds. Agent scoring combines robust fee deviations and Isolation Forest with references and scaling learned from train agents only. Failed refits preserve the previous fitted model/calibration atomically. Gender, age, region, group_label and agent_type are evaluation-only and excluded from scoring, including peer grouping. Final evaluation artifacts and configured observation-window/report feature repairs are still pending.

## Evaluation and results

Pending: corrected reproducible command, versioned JSON/Markdown results and saved inference bundle. Report both rules and models on validation, held-out seed2026 agents and distribution-shifted test. Validation calibration diagnostics must be distinguished from final independent test estimates. Include precision/recall, calibration, honest-high-volume false flags, session and observed-report ablations, approved skimming profiles and fairness denominators.

Inherited report numbers are provisional and excluded here because the audit found fit/scoring and explanation defects. No target score or superiority claim will be assumed.

## Simulated impact

Pending:30/50/70% adoption scenarios. Any prevented-loss number is a synthetic counterfactual under explicit assumptions about eligible assisted cash-outs and mandate compliance, not measured benefit. Show eligible loss and total injected loss separately. Financial defaults, including1.5% fee,5000BDT mandate cap and25000BDT daily limit, are ASSUMPTIONS, never actual upay figures.

## Responsible AI and security

Models prioritize outreach/review and never authorize or deny cash-out. The approved flow uses customer confirmation, bounded attempts, hashed one-time codes, expiry, scope, ledger checks and human review. Fairness gaps must be reported even when the target is missed. No claim of coercion, lie detection or speaker identity verification is made. Audio retention is disabled by policy; keypad/Bangla amount parsing is the essential path.

Verified synthetic security behavior at T024:

| Control | Verified evidence |
|---|---|
| Scope and role | Actor headers alone rejected; training-cohort customer access forbidden; customer code issuance forbidden |
| Amount comprehension | Bangla keypad accepted; invalid numeric inputs422; first mismatch remains requested, second rejects |
| Code use | Bound agent issues once; expiry unchanged; successful redemption followed by replay rejection |
| Lockout and durability | Third wrong code rejected; persisted attempts, receipt and cases survive API restart |
| Financial integrity |3,000BDT payout, assumed45BDT fee,3,045BDT debit; reseed preserves remaining46,955BDT |
| Cash report and review | Identical repeated report idempotent, changed report rejected; actual gap creates a case; human escalation grants no redemption |

## Scalability and integration

A channel-facing API could be piloted with a financial-service provider after governed requirements, security review and real-data validation. This hackathon prototype is not integrated with upay and does not execute real transactions. The verified durable local API demo remains scoped to synthetic identities.

## Innovation and limitations

The contribution is the combination of scoped cash-out authority, independent amount confirmation, behavioral outreach and explainable review. Prior-art comparison requires sourced research before claiming novelty. Synthetic distributions cannot establish real accuracy; sparse injected skimmers limit agent estimates; validation calibration makes validation scores diagnostic. Voice/LLM/graph extensions may be omitted to preserve a reliable keypad demo and reproducible baseline comparison.

## Disclosures

Development tools: Codex orchestration/review, Antigravity IDE for inherited work, and Antigravity CLI(agy) for implementation repairs. Application components include Python/FastAPI/PostgreSQL, React/Vite, LightGBM/scikit-learn/SHAP and standard open-source dependencies. Data are generated locally. No external inference API is required for the current verified console; receipts use validated templates. GitHub hosts source; Render deployment is planned through the human's dashboard and remains unverified.

## Appendix and completion items

Repository: https://github.com/irfan0072/sathi-ai-dev-fest-2026

Before submission: insert verified final results and reproduce command, finished flow/API/schema references, screenshots, public URL and limitations; source problem/prior-art claims; dry-run demo; verify README from clean clone; record human registration/submission facts without assuming them.
