# Sathi Console Mock API Contract

This contract defines all API endpoints, query/body payloads, success responses, error formats, and realistic mock fixtures so the frontend team can develop and test the **Sathi Console** and **Phone Simulator** immediately against a mock server without waiting for backend deployment.

Base URL prefix: `/api/v1`
Default local mock server port: `18000` (or `18001` if running against live dev server)

---

## 1. Quick Start: Running the Mock Server

You can run a local mock server using **FastAPI** (stdlib/pre-installed in `.venv`), **MSW (Mock Service Worker)**, or **json-server**.

### Option A: Built-in Python Mock Runner (Zero Dependencies)
A lightweight mock server is provided at `scripts/mock_server.py`:
```sh
# Run from repository root
PYTHONPATH=backend .venv/bin/python scripts/mock_server.py --port 18000
```
This serves all mock endpoints below with interactive in-memory state.

### Option B: Frontend Vite Proxy / Mock
In `frontend/vite.config.js`, API requests to `/api/v1` can be forwarded to `http://127.0.0.1:18000`.

---

## 2. Global Error Envelope
All error responses (4xx, 5xx) return the standard JSON envelope:
```json
{
  "error": {
    "code": "MANDATE_NOT_FOUND",
    "message": "Mandate e5b87120-a6bb-49e0-8fa3-9f899e3a6a12 does not exist."
  }
}
```

Standard Error Codes:
- `400`: `BAD_REQUEST`, `INVALID_PARAMETER`
- `401`: `UNAUTHORIZED`, `INVALID_ONE_TIME_CODE`
- `403`: `FORBIDDEN`
- `404`: `NOT_FOUND`, `USER_NOT_FOUND`, `AGENT_NOT_FOUND`, `MANDATE_NOT_FOUND`
- `409`: `ACTIVE_MANDATE_EXISTS`, `ALREADY_REDEEMED`
- `410`: `MANDATE_EXPIRED`
- `422`: `INVALID_AMOUNT`, `LIMIT_EXCEEDED`
- `423`: `ACCOUNT_LOCKED`

---

## 3. Endpoints & Mock Payloads

### 3.1 `POST /api/v1/mandates/request`
Requested by: **Agent Terminal**
Purpose: Agent requests a cash-out mandate on behalf of an assisted customer.

#### Request Payload
```json
{
  "user_id": "U_42_000123",
  "agent_id": "A_000042",
  "amount": 3000.00,
  "purpose": "cash_out"
}
```

#### Success Response `201 Created`
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "user_id": "U_42_000123",
  "agent_id": "A_000042",
  "amount": 3000.00,
  "status": "requested",
  "next": "verify",
  "verification_modes": ["keypad", "voice"],
  "created_at": "2026-10-02T18:30:00Z"
}
```

---

### 3.2 `POST /api/v1/mandates/{id}/verify`
Requested by: **Phone Simulator / Customer Channel**
Purpose: Customer verifies comprehension of cash-out amount in Bangla via keypad digits or spoken voice.

#### Request Payload
```json
{
  "mode": "keypad",
  "stated_amount": 3000.00,
  "attempt": 1
}
```

#### Success Response `200 OK` (Match -> Active Mandate Issued)
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "outcome": "match",
  "decision": "ISSUE_MANDATE",
  "status": "active",
  "expires_at": "2026-10-02T18:45:00Z",
  "code_delivery": "agent_terminal",
  "one_time_code": "849201",
  "customer_prompt_bn": "আপনার ৩,০০০ টাকা ক্যাশ-আউট অনুমোদিত হয়েছে। এজেন্টকে কোডটি বলুন।"
}
```

#### Mismatch Response `200 OK` (Mismatch -> Sent to Analyst Case Queue)
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "outcome": "mismatch",
  "decision": "REVIEW",
  "status": "requested",
  "case_id": 1042,
  "reason": "Amount mismatch: requested 3000 BDT, customer entered 2500 BDT",
  "customer_prompt_bn": "আপনার টাকার পরিমাণে অমিল পাওয়া গেছে। পর্যালোচনার জন্য পাঠানো হয়েছে।"
}
```

---

### 3.3 `POST /api/v1/mandates/{id}/redeem`
Requested by: **Agent Terminal**
Purpose: Agent submits customer's 6-digit one-time code to complete cash-out.

#### Request Payload
```json
{
  "code": "849201"
}
```

#### Success Response `200 OK`
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "txn_id": 9912042,
  "amount": 3000.00,
  "fee": 45.00,
  "status": "redeemed",
  "redeemed_at": "2026-10-02T18:32:15Z"
}
```

---

### 3.4 `POST /api/v1/mandates/{id}/confirm-cash`
Requested by: **Phone Simulator / Customer Channel**
Purpose: Customer reports physical cash received from the agent.

#### Request Payload
```json
{
  "cash_received": 2955.00
}
```

#### Success Response `200 OK` (No Gap or within Tolerance)
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "cash_received": 2955.00,
  "expected_payout": 2955.00,
  "gap": 0.00,
  "flagged": false
}
```

#### Flagged Gap Response `200 OK` (Cash Gap exceeds Tolerance)
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "cash_received": 2700.00,
  "expected_payout": 2955.00,
  "gap": 255.00,
  "tolerance_bdt": 60.00,
  "flagged": true,
  "case_id": 1043,
  "note": "Reported cash gap 255 BDT exceeds tolerance 60 BDT. Flagged for review."
}
```

---

### 3.5 `POST /api/v1/mandates/{id}/revoke`
Requested by: **Phone Simulator / Customer or Analyst**
Purpose: Cancel an active mandate immediately.

#### Request Payload
```json
{
  "reason": "Customer cancelled cash-out request"
}
```

#### Success Response `200 OK`
```json
{
  "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
  "status": "revoked",
  "revoked_at": "2026-10-02T18:33:00Z"
}
```

---

### 3.6 `GET /api/v1/users/{id}/assisted-score`
Requested by: **Analyst Console**
Purpose: Explainable assisted-user classifier output with calibrated probability and SHAP values.

#### Success Response `200 OK`
```json
{
  "user_id": "U_42_000123",
  "score": 0.884,
  "assisted": true,
  "confidence": 0.912,
  "model_version": "lgbm_assisted_v1",
  "top_reasons": [
    {
      "feature": "top_agent_share",
      "display_name": "শীর্ষ এজেন্টে লেনদেনের হার (Top-Agent Share)",
      "value": 0.92,
      "peer_median": 0.38,
      "shap_impact": "+0.34",
      "direction": "positive"
    },
    {
      "feature": "hours_credit_to_cashout",
      "display_name": "টাকা জমার পর উত্তোলনের সময় (Hours Credit-to-Cashout)",
      "value": 3.5,
      "peer_median": 48.0,
      "shap_impact": "+0.28",
      "direction": "positive"
    },
    {
      "feature": "withdrawn_fraction",
      "display_name": "উত্তোলিত ব্যালেন্সের অনুপাত (Withdrawn Fraction)",
      "value": 0.96,
      "peer_median": 0.45,
      "shap_impact": "+0.19",
      "direction": "positive"
    }
  ]
}
```

---

### 3.7 `GET /api/v1/agents/{id}/risk`
Requested by: **Analyst Console**
Purpose: Agent anomaly ranking comparing agent behavior against peer groups.

#### Success Response `200 OK`
```json
{
  "agent_id": "A_000042",
  "risk": 0.865,
  "level": "HIGH",
  "peer_group": "region=rajshahi,volume=high",
  "model_version": "isolation_forest_peer_z_v1",
  "reasons": [
    {
      "feature": "fee_ratio_vs_official",
      "display_name": "ফি অনুপাত (Fee Ratio vs Official 1.5%)",
      "value": 1.35,
      "peer_median": 1.00,
      "z_score": 3.82
    },
    {
      "feature": "assisted_customer_fraction",
      "display_name": "সহায়তা গ্রহণকারী গ্রাহক অনুপাত (Assisted Share)",
      "value": 0.64,
      "peer_median": 0.20,
      "z_score": 4.10
    },
    {
      "feature": "unexplained_cash_gap_rate",
      "display_name": "গ্রাহকের নগদ পার্থক্যের হার (Customer Cash Gap)",
      "value": 0.18,
      "peer_median": 0.01,
      "z_score": 5.20
    }
  ]
}
```

---

### 3.8 `GET /api/v1/outreach`
Requested by: **Analyst Console (Outreach View)**
Purpose: Prioritized list of high-probability assisted users for digital literacy outreach or mandate setup.

#### Success Response `200 OK`
```json
{
  "total": 420,
  "items": [
    {
      "user_id": "U_42_000123",
      "assisted_score": 0.942,
      "primary_agent_id": "A_000042",
      "monthly_volume_bdt": 4500.00,
      "risk_band": "high_assistance",
      "outreach_recommended": "assisted_mandate_enrolment",
      "last_active": "2026-10-02T12:30:00Z"
    },
    {
      "user_id": "U_42_000512",
      "assisted_score": 0.895,
      "primary_agent_id": "A_000015",
      "monthly_volume_bdt": 3000.00,
      "risk_band": "high_assistance",
      "outreach_recommended": "assisted_mandate_enrolment",
      "last_active": "2026-10-02T10:15:00Z"
    }
  ]
}
```

---

### 3.9 `GET /api/v1/cases`
Requested by: **Analyst Console (Review Queue)**
Purpose: Open review cases resulting from amount mismatches, mandate cap exceedances, or agent flags.

#### Success Response `200 OK`
```json
{
  "total": 12,
  "cases": [
    {
      "case_id": 1042,
      "mandate_id": "e5b87120-a6bb-49e0-8fa3-9f899e3a6a12",
      "user_id": "U_42_000123",
      "agent_id": "A_000042",
      "reason": "Amount mismatch: requested 3000 BDT, customer stated 2500 BDT",
      "status": "open",
      "severity": "HIGH",
      "created_at": "2026-10-02T18:31:00Z",
      "evidence": {
        "requested_amount": 3000.00,
        "stated_amount": 2500.00,
        "agent_risk_score": 0.865,
        "user_assisted_score": 0.884,
        "previous_cases_count": 0
      }
    }
  ]
}
```

---

### 3.10 `POST /api/v1/cases/{id}/decision`
Requested by: **Analyst Console**
Purpose: Record human reviewer decision on a case.

#### Request Payload
```json
{
  "decision": "approved",
  "reviewer": "analyst_karim",
  "note": "Contacted customer; customer intended 3,000 BDT cash-out. Approved manually."
}
```

#### Success Response `200 OK`
```json
{
  "case_id": 1042,
  "status": "approved",
  "decision": "approved",
  "reviewer": "analyst_karim",
  "resolved_at": "2026-10-02T18:35:10Z"
}
```

---

### 3.11 `GET /api/v1/receipts/{txn_id}`
Requested by: **Customer Channel / Console**
Purpose: Plain-language, audited receipt text in Bangla.
*Security invariant*: All numbers in receipt text are strictly validated against transaction DB values.

#### Success Response `200 OK`
```json
{
  "txn_id": 9912042,
  "user_id": "U_42_000123",
  "agent_id": "A_000042",
  "amount_bdt": 3000.00,
  "fee_bdt": 45.00,
  "payout_bdt": 2955.00,
  "ts": "2026-10-02T18:32:15Z",
  "receipt_text_bn": "সাথী ক্যাশ-আউট সফল হয়েছে। উত্তোলন: ৩,০০০ টাকা, ফি: ৪৫ টাকা (১.৫%), প্রাপ্ত অর্থ: ২,৯৫৫ টাকা। এজেন্ট: A_000042, ট্রানজ্যাকশন আইডি: 9912042।"
}
```

---

### 3.12 `GET /api/v1/metrics/summary`
Requested by: **Analyst Console (Metrics Dashboard)**
Purpose: Aggregate evaluation metrics, rule baseline comparisons, fairness metrics, and adoption simulations.

#### Success Response `200 OK`
```json
{
  "evaluation_dataset": "synthetic_seed_4242",
  "assisted_classifier": {
    "model": "LightGBM",
    "pr_auc": 0.942,
    "roc_auc": 0.961,
    "f1_score": 0.891,
    "baseline_rule_pr_auc": 0.785,
    "lift_over_baseline": "+19.9%"
  },
  "agent_anomaly": {
    "model": "Isolation Forest + Robust Peer Z-Score",
    "precision_at_k": 0.85,
    "recall_skimmers": 0.90,
    "false_flag_rate_honest_high_volume": 0.05,
    "baseline_rule_precision": 0.62
  },
  "fairness_slices": {
    "max_tpr_gap": 0.065,
    "target_tpr_gap": 0.10,
    "compliant": true,
    "by_gender": {
      "female": {"tpr": 0.892, "fpr": 0.041},
      "male": {"tpr": 0.915, "fpr": 0.038}
    },
    "by_urban_rural": {
      "urban": {"tpr": 0.908, "fpr": 0.039},
      "rural": {"tpr": 0.885, "fpr": 0.044}
    }
  },
  "impact_simulation": {
    "adoption_scenarios": [
      {
        "adoption_rate": "30%",
        "pin_disclosure_reduction": "30.0%",
        "simulated_loss_prevented_bdt": 185000.00
      },
      {
        "adoption_rate": "50%",
        "pin_disclosure_reduction": "50.0%",
        "simulated_loss_prevented_bdt": 312000.00
      },
      {
        "adoption_rate": "70%",
        "pin_disclosure_reduction": "70.0%",
        "simulated_loss_prevented_bdt": 435000.00
      }
    ]
  }
}
```
