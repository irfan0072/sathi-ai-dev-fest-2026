# Architecture

## 1. Principle
INPUT -> INTELLIGENCE -> ACTION. Data preparation, model inference, business rules and LLM text are separate layers.

## 2. Flow
```
Synthetic data -> Feature layer -> Models ----------------+
                                                          v
Agent terminal -> Mandate API -> Policy engine (rules) -> Decision
                       |              ^                    |
                       v              | agent/user risk    v
              Verification service ---+            Audit log + Cases
              (voice or keypad)                            |
                       |                                   v
              Phone simulator                       Analyst console
                                                    (human review)
```

## 3. Components
| Component | Responsibility | Not allowed to |
|---|---|---|
| Data generator | Creates synthetic users, agents, transactions, sessions with injected patterns | Use real PII |
| Feature layer | Per-user and per-agent aggregates, peer groups | Call the LLM |
| Assisted-user model | Score likelihood a user is operated with help | Make allow/deny decisions |
| Agent anomaly model | Rank agents by deviation from peers | Penalise agents automatically |
| Policy engine | Deterministic allow / review / deny / issue mandate | Be replaced by an LLM prompt |
| Verification service | Compare customer's stated amount to requested amount (voice or keypad) | Claim to detect coercion or lying |
| Copilot | Wording of receipts and case narratives from structured evidence | Produce numbers or decisions |
| Console | Review queue, outreach list, metrics | Bypass the audit log |

## 4. Mandate lifecycle
`requested -> verified -> active -> redeemed | expired | revoked | rejected`
- Bound to one agent, purpose = cash_out, amount cap, TTL (config), single use.
- Only a hash of the one-time code is stored. Every transition is written to audit_log with model versions.

## 5. Policy rules (initial)
1. No answer in verification -> DENY.
2. Stated amount mismatch -> REVIEW.
3. Amount above user cap -> REVIEW.
4. Agent risk >= HIGH -> REVIEW.
5. Otherwise -> ISSUE_MANDATE.
All thresholds come from `data/config.yaml` so on-site changes are config edits.

## 6. Scale and integration path
- API is channel-agnostic: app, USSD menu, SMS, IVR all call the same endpoints.
- Replace synthetic tables with read-only views of governed, anonymised or aggregated upay data for a controlled pilot.
- Agent terminal integration point: mandate request/redeem calls from the existing agent workflow.
- Future: share hashed risk signals across MFS providers (concept only, not built).

## 7. Deployment
Postgres + API + console via docker compose locally; one live URL for judges. Deploy a skeleton in the first hours, redeploy continuously.
