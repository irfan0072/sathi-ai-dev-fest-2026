# Responsible AI and security

All data and transaction demonstrations are synthetic. Current completion evidence is in handoff.md; planned controls below are not a claim of production readiness.

| Principle | Required behavior | Evidence/gate |
|---|---|---|
| Privacy | No real PII/PIN; parsed amount only, no stored audio | Config/schema; durable API verifiedT024 |
| Explanation | SHAP explains same base model in raw log odds; train-derived peer reasons | T023 tests; console artifact wiring pendingT025 |
| Fairness | Demographics evaluation-only; include slice denominators and misses | Corrected final report pendingT023b |
| Security | Durable hashed codes, expiry, replay/attempt locks, scoped tokens, ownership, ledger rules | T024 DB/security/concurrency tests and actual HTTP flow pass |
| Human oversight | Models prioritize review/outreach; review never redeems | API verifiedT024; console pendingT025 |
| Transparency | Illustrative samples labelled; missing metrics unavailable; fees/impact ASSUMPTIONS | T022 verified; final evidence pending |
| No harmful automation | No score-based authorization, denial or automatic agent penalties | Approved design and focused tests |

Threats to test include guessing/replay, concurrent spending, ownership spoofing, expired tokens, client attempt-counter manipulation, malformed/ambiguous amounts, prompt-like free text and receipt number injection. Public demo principals are explicitly synthetic and low privilege; no admin/policy writes. Hashing alone is insufficient without attempt limits and scope. Signed tokens require a nondefault server secret; credentials remain out of Git.

Customer confirmation checks the stated amount only. It cannot detect coercion, verify comprehension beyond that response, identify speakers or guarantee physical cash delivery. Caps and cash reports can support review but cannot eliminate collusion. Analyst decisions update durable case/audit state without granting mandate authority.

Synthetic distributions cannot establish real-world accuracy or prevented loss. Sparse skimmers and small fairness slices limit estimates; undefined rates must remain unavailable. Adoption30/50/70 estimates are idealized counterfactuals with eligible-loss denominators and explicit assumptions. Validation used for calibration is a diagnostic cohort; final test estimates must use frozen models. A governed pilot is required before any real deployment.

LLM, voice and graph extensions may be omitted. Current receipts use validated templates; no external LLM inference or voice quality claim is necessary for the essential keypad demo.
