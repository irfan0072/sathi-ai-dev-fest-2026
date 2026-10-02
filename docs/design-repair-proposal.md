# Approved design repair — implementation pending

Human approved this design on 2 October 2026: “Approve the proposed repair design”. Each change remains implementation-pending until its task passes independent verification. This proposal closes audit gaps while preserving the existing component boundaries and approved simulation values. All amounts/rates are ASSUMPTIONS, not actual upay figures.

## Model/evaluation boundary repair

- Remove region from anomaly peer grouping: protected metadata must not influence scores, including indirect cohort grouping. Compute volume bands from observed cash-out totals using train-derived boundaries, never from generated volume_band (which depends on agent_type).
- Fit agent reference statistics, Isolation Forest and score scaling on train agents only; score validation/test/shift without refitting. Freeze thresholds using config and validation only. Retain numeric behavioral features and the rule baseline.
- Fit assisted LightGBM on train, calibrate on the disjoint validation cohort using a frozen estimator, and explain that same underlying fitted estimator with SHAP explicitly labelled raw log-odds contribution, not calibrated probability contribution. No protected metadata or group label enters features/calibration.
- Correct existing evaluation plan implementation: ordinary unit tests use small fixtures, not final test scoring. One documented final-run command validates manifest/hash/disjointness, compares both baselines/models on validation, test and shifted test, records seeds/counts/config/data/package hashes, saves JSON + Markdown + inference artifacts. No test threshold tuning. Config remains source of thresholds. Sanity ceiling applied to validation; if >0.98 widen overlap and disclose rather than tune to score.
- Skimming sweep uses approved generator intensity profiles; cash-gap ablation uses noisy customer reports only, never actual payout truth or skimmer labels. Where signals unavailable, mark unsupported rather than report zero-feature ablation.

## Durable mandate and authenticated demo proposal

Add migration002; never modify applied migration001 or overwrite synthetic ledger data. Proposed database delta:

- mandates.code_hash may be NULL only in requested/verified states; active/redeemed must have a 64-character hash. Existing populated values preserved.
- Add verification_attempts INTEGER NOT NULL DEFAULT0 and redemption_attempts INTEGER NOT NULL DEFAULT0 with nonnegative checks; keep current status enum (use rejected for locked mandate rather than inventing unsupported locked status).
- Unique partial index on user_id for live statuses requested/verified/active; existing duplicate detection aborts migration instead of deleting data.
- Existing verification_events, cases, review_actions, audit_log, transactions and sessions tables store durable records; no parallel in-memory source of truth. Daily total computed from cash-out ledger in Asia/Dhaka timezone. User/mandate row locks enforce caps, balance, daily total, single-use and concurrent redemption. Financial arithmetic Decimal cents.

Proposed API delta:

- POST /api/v1/auth/demo-login: synthetic whitelisted demo principals only; server-generated signing secret (Render generateValue), signed short-lived bearer token scopes agent/customer_channel/analyst. No admin role or policy mutation exposed. No real customer credentials. X-Actor is never authentication. Low-privilege demo accounts are openly labelled synthetic; roles/subject ownership enforced on every existing endpoint.
- POST /mandates/{id}/verify retains keypad/mode and stated_amount, accepts normalized Bangla numeric text as well as JSON number; server increments attempts (client attempt becomes ignored compatibility metadata). Response on match status verified, decision ISSUE_MANDATE, code_delivery agent_terminal, no plain code in customer response.
- NEW POST /mandates/{id}/issue-code: authenticated bound agent only, exactly once after customer verification. Generates cryptographic6digit code, persists hash, activates mandate, returns code only to terminal. Expiry starts at verification and does not extend on retrieval/redeem. Lost delivery requires revoke/re-request; no plaintext code is persisted.
- Redemption failures persisted; proposed config max_redemption_attempts3 (distinct from approved verification2). Exceeding limit returns423, changes to rejected and records case/audit. Exact expiry boundary is expired (now >= expires_at). Config thresholds fail closed if missing/invalid.
- Redeem appends real ledger transaction (fee explicitly computed from assumed rate0.015; balance debit amount+fee), with full cash amount delivered. This changes existing fee0 example; UI shows amount and fee before customer verification.
- Cash confirmation allowed only after redemption, exactly once/idempotent for identical repeated report; stored verification_event.cash_received_reported and gap case within same transaction. Receipt reads actual ledger transaction and validated template, no LLM needed.
- Unknown users/agents/transactions/cases404; unauthenticated401, wrong role/ownership403. Human review changes case status and audit only; never automatically redeems or grants allow/deny from model scores.

Approval scope: adopt model boundary repair and migration/API design above. Deployment account actions and paid plans remain separate human actions. No data deletion or architecture expansion requested.
