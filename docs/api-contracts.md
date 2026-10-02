# API Contracts (FastAPI, JSON)

Base path `/api/v1`. Roles: `agent`, `analyst`, `admin`, `customer_channel` (phone simulator / IVR / USSD gateway). All endpoints require auth; every call writes to `audit_log`. Amounts in BDT. Errors use `{ "error": {"code": "...", "message": "..."} }`.

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | /mandates/request | agent | Agent requests a cash-out mandate for a customer |
| POST | /mandates/{id}/verify | customer_channel | Submit stated amount (keypad or voice) |
| POST | /mandates/{id}/redeem | agent | Redeem with one-time code |
| POST | /mandates/{id}/confirm-cash | customer_channel | Customer reports cash received |
| POST | /mandates/{id}/revoke | customer_channel, analyst | Revoke an active mandate |
| GET | /users/{id}/assisted-score | analyst | Assisted-user score + reasons |
| GET | /agents/{id}/risk | analyst | Agent risk + peer comparison |
| GET | /outreach | analyst | Ranked list of likely assisted users |
| GET | /cases | analyst | Review queue |
| POST | /cases/{id}/decision | analyst | Approve / deny / escalate with note |
| GET | /receipts/{txn_id} | customer_channel | Plain-language receipt text (Bangla) |
| GET | /metrics/summary | analyst | Baseline vs model, fairness, impact simulation |

## POST /mandates/request
Request
```json
{ "user_id": "U_000123", "agent_id": "A_0042", "amount": 3000, "purpose": "cash_out" }
```
Response 201
```json
{ "mandate_id": "uuid", "status": "requested", "next": "verify", "verification_modes": ["keypad", "voice"] }
```
Errors: 404 unknown user/agent; 409 active mandate already exists; 422 amount invalid.

## POST /mandates/{id}/verify
Request
```json
{ "mode": "keypad", "stated_amount": 3000, "attempt": 1 }
```
Response 200
```json
{ "outcome": "match", "decision": "ISSUE_MANDATE", "status": "active", "expires_at": "ISO-8601",
  "code_delivery": "agent_terminal" }
```
Other decisions: `REVIEW` (case_id returned), `DENY`. The one-time code is shown only to the agent terminal; only its hash is stored.

## POST /mandates/{id}/redeem
Request `{ "code": "123456" }`  Response 200 `{ "txn_id": 9912, "amount": 3000, "fee": 0, "status": "redeemed" }`
Errors: 401 bad code; 410 expired; 409 already used; 423 locked after repeated failures.

## POST /mandates/{id}/confirm-cash
Request `{ "cash_received": 2800 }`  Response 200 `{ "gap": 200, "flagged": true }`  (a gap above the config tolerance raises an agent signal and a case)

## GET /agents/{id}/risk
```json
{ "agent_id": "A_0042", "risk": 0.86, "level": "HIGH",
  "reasons": [{"feature": "fee_ratio_vs_official", "value": 1.35, "peer_median": 1.0}],
  "peer_group": "region=Rajshahi,volume=high", "model_version": "agent_anomaly_v1" }
```

## GET /receipts/{txn_id}
Returns Bangla text plus numbers drawn from the database. The LLM may reword wording but is not allowed to alter numbers (validated by a post-check that compares numbers in the text with database values).

## Versioning and config
Policy version and model versions are included in every decision log. Thresholds are read from `data/config.yaml` at start and on reload.
