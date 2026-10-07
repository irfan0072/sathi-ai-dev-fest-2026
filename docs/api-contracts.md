# Synthetic demo API contract

Base `/api/v1`. All financial values are simulation ASSUMPTIONS, never actual upay figures. Health is public diagnostic information; business routes require scoped bearer authentication. X-Actor is not authentication. No admin or policy-write role.

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | /auth/demo-login | Public synthetic fixture login | Signed, expiring configured-principal token |
| POST | /mandates/request | Bound agent | Request amount; display payout, fee and total debit |
| POST | /mandates/{id}/verify | Owning customer_channel | Normalize keypad amount; server-count attempts |
| POST | /mandates/{id}/issue-code | Bound agent | Terminal code exactly once after verification |
| POST | /mandates/{id}/redeem | Bound agent | Atomic code check and ledger debit |
| POST | /mandates/{id}/confirm-cash | Owning customer_channel | Customer report after redemption |
| POST | /mandates/{id}/revoke | Owning customer_channel, analyst | Revoke without granting transaction authority |
| GET | /users/{id}/assisted-score | Analyst | Verified synthetic snapshot score/reasons |
| GET | /agents/{id}/risk | Analyst | Snapshot risk and train-derived volume peers |
| GET | /outreach | Analyst | Verified synthetic snapshot ranking |
| GET | /cases | Analyst | Durable human-review queue |
| POST | /cases/{id}/decision | Analyst | Review and audit; does not redeem |
| GET | /receipts/{txn_id} | Owning customer_channel | Actual redeemed ledger receipt |
| GET | /metrics/summary | Analyst | Verified held-out evaluation artifact |

Agent scope permits configured demo customers only, never training/validation/test ledger users. Model/metrics routes depend on T023b/T025 artifacts; unavailable artifacts produce unavailable responses. Unknown records404; missing/invalid authentication401; wrong role/ownership403.

## Lifecycle and amounts

Request fields: user_id, agent_id, amount, purpose=cash_out. A3000BDT request has an assumed45BDT fee,3045BDT debit and3000BDT full payout. Limits/fees/attempts come from data/config.yaml. Financial calculations use decimal cents. Keypad parsing accepts positive finite JSON numbers or numeric text, Bangla digits and valid comma grouping; ambiguous text, booleans, excess precision and nonfinite values are rejected. Speech recognition is not implemented.

Verification fields: mode=keypad, stated_amount; legacy client attempt is ignored as authority. Matching changes requested→verified and starts15-minute expiry. Customer responses never contain a code. First mismatch remains requested; second mismatch is rejected under the assumed two-attempt limit. Mismatch creates durable review evidence and bounded server attempts; human review cannot bypass deterministic policy.

Issuance changes verified→active, stores only64-hex SHA256 hash and returns a cryptographic6-digit code to the bound agent once. It does not extend expiry. Lost delivery requires revoke/new request. Unissued requested/verified/rejected/expired/revoked may have NULL hashes; active/redeemed require a valid hash.

Redemption field: code. Database locks enforce expiry at now>=expires_at, single use, balance, mandate cap and Dhaka-calendar daily cash-out limit. Wrong-code attempts persist even when the API returns an error; configured third failure rejects the mandate and creates case/audit records. Success links the actual transaction and returns its amounts/fee. Replay is rejected.

Confirmation field: cash_received. Only redeemed mandates qualify. Identical repeat is idempotent; changed repeat is rejected. Gap tolerance max(50BDT,2% of amount) is an ASSUMPTION. Excess gaps create actual cases; they do not prove intent or coercion. Receipts use the redeemed transaction timestamp/exact amounts. Templates cannot introduce extra numbers.

## Provenance and authority

Model signals support outreach/human review only. Gender, age band, region, group labels and agent types never influence features, calibration, peer scoring or authorization. Artifact rows describe a fixed synthetic snapshot, separate from runtime demo balances. SHAP explains fitted base-model raw log-odds, not calibrated probability contributions. Missing artifacts are unavailable.

Attempts, verification events, cases, ledger records and audit logs are PostgreSQL-backed. Signing secrets belong only in ignored environment configuration. Public synthetic demo PINs are fixtures, not real customer credentials.

## Runtime readiness

`GET /health` returns200 only when signing is configured, the curated bundle passes hashes/current-config validation, and the database probe finds migrations, configured demo principals and their ledger. Payload keys: `status`, `database` (`ready`/`unavailable`; requires every migration file to be applied), `auth_signing`, `artifacts` (`verified`/`unavailable`), `integrations` (always `not_verified_by_health`: healthy does not mean a real call, SMS or MFS integration was verified) and `deployment_mode`. Unready state returns503/degraded without underlying exceptions or credentials. Existing business routes and schema are unchanged. Startup validates before database writes, applies001/002 idempotently and seeds only namespace777 without replenishing spent balances.

## Live channels and intelligence (3 October 2026)

Migration 003 adds `voice_calls`, `mandate_risk` and `case_briefs` (additive only). `POST /mandates/request` also returns `risk` {score, band, step_up, engine_version}; the signal trace is analyst-only. Optional enforcement (`SATHI_STEP_UP_ENFORCED=true`) makes `/verify` return `403 STEP_UP_REQUIRED` unless step-up is `keypad_or_call`. Full route table, roles and security notes: [live-mode.md](live-mode.md#new-api-routes).


## Final-round additions (7 October 2026; local and synthetic, contracts unconfirmed with any partner)

All routes below are additive. None of them moves money.

| Route | Roles | Purpose |
|---|---|---|
| `GET /api/v1/deployment` | public | `{mode, simulated_only, management_read_only, real_providers_allowed, online_ai_allowed, label}` |
| `POST /api/v1/callcenter/tasks/{id}/followup/claim` | supervisor | Take the independent follow-up of a suspicious check (one holder, conditional update) |
| `POST /api/v1/callcenter/tasks/{id}/followup/assign` | super_admin | Assign it to an active supervisor |
| `POST /api/v1/callcenter/tasks/{id}/followup` | supervisor (holder), super_admin | `{outcome: attempted\|reached_independently\|uncertain\|unreachable, channel: registered_number\|in_person, note?}`. Unknown fields (a phone number) are rejected with 422. `reached_independently` with `registered_number` is refused (`SAME_HANDSET_NOT_INDEPENDENT`) |
| `GET /api/v1/callcenter/queue?scope=followup` | supervisor, super_admin | Suspicious checks needing independent contact (a supervisor sees the unassigned list and their own) |
| `POST /api/v1/cases/{id}/decision` (decision `approved`) | analyst, super_admin, supervisor | Returns `409 INDEPENDENT_CONTACT_REQUIRED` while the linked check's follow-up is `required`, `attempted`, `uncertain` or `unreachable` |
| `POST /api/v1/cases/{id}/brief` | analyst, super_admin, supervisor | Adds `mode` (`deterministic` or `llm_guarded`), `mode_label`, `guard_limits`, `facts_shared_externally` |
| `GET /api/v1/ops/workflow-evidence` | supervisor, analyst, super_admin | Observed workflow counts with numerators and denominators from this database. `field_impact` is always `null` |
| `GET /api/v1/ops/economics` | supervisor, analyst, super_admin | Assumption-based cost and break-even model. No invoices, no measured loss prevention |
| `GET /api/v1/voice/config` | agent, customer, analyst, super_admin | Adds `speech_input`: no custom ASR model, `validated_dialects: []`, the missing-confidence policy |

**Provider-recorded cash-out events (contract unconfirmed).** An authenticated cash-out/KYC feed
from an MFS operator is not implemented. If one is added, a provider-recorded cash-out must be
recorded as an event only: it must never debit the ledger a second time, it must be idempotent on
the provider's event id, and its signature must be verified before any state change. The existing
agent API (`POST /api/v1/cashouts`) is the only entry today.

**Call placement failure.** `POST /api/v1/cashouts` still returns 201 when the cash-out is
committed but the call could not be placed. The task is retried with back-off up to
`calls.max_auto_attempts`, then moves to the supervisor queue with reason `provider_failure`.
If the provider may have accepted the call (timeout, 5xx), no second call is placed until the
live call settles. A delivery error never reverses or debits the ledger.
