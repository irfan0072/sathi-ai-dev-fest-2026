-- Sathi PostgreSQL schema (design). All data synthetic.
CREATE TABLE users (
  user_id TEXT PRIMARY KEY,
  group_label TEXT CHECK (group_label IN ('independent_urban','independent_rural','assisted_allowance','assisted_family')), -- generator ground truth, never a model input
  gender TEXT, age_band TEXT, region TEXT, urban_rural TEXT,          -- evaluation slices only
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE agents (
  agent_id TEXT PRIMARY KEY,
  region TEXT, volume_band TEXT,
  agent_type TEXT CHECK (agent_type IN ('normal','high_volume_honest','skimmer')),  -- ground truth for evaluation only
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE transactions (
  txn_id BIGSERIAL PRIMARY KEY,
  user_id TEXT REFERENCES users, agent_id TEXT REFERENCES agents,
  txn_type TEXT CHECK (txn_type IN ('credit','cash_out','send','bill_pay')),
  credit_source TEXT,                -- allowance | remittance | salary | add_money
  amount NUMERIC(12,2) NOT NULL, fee NUMERIC(12,2) DEFAULT 0,
  balance_after NUMERIC(12,2), channel TEXT,   -- app | ussd | agent_initiated
  ts TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON transactions (user_id, ts);
CREATE INDEX ON transactions (agent_id, ts);
CREATE TABLE sessions (
  session_id BIGSERIAL PRIMARY KEY,
  user_id TEXT REFERENCES users, txn_id BIGINT REFERENCES transactions,
  pin_retries INT DEFAULT 0, pin_entry_ms INT, steps INT, ts TIMESTAMPTZ NOT NULL
);
CREATE TABLE mandates (
  mandate_id UUID PRIMARY KEY,
  user_id TEXT REFERENCES users, agent_id TEXT REFERENCES agents,
  purpose TEXT NOT NULL DEFAULT 'cash_out', amount_cap NUMERIC(12,2) NOT NULL,
  code_hash TEXT NOT NULL,           -- never store the code itself
  status TEXT NOT NULL CHECK (status IN ('requested','verified','active','redeemed','expired','revoked','rejected')),
  expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  redeemed_txn_id BIGINT REFERENCES transactions
);
CREATE TABLE verification_events (
  event_id BIGSERIAL PRIMARY KEY,
  mandate_id UUID REFERENCES mandates,
  mode TEXT CHECK (mode IN ('keypad','voice')),
  stated_amount NUMERIC(12,2),       -- parsed number only; no audio stored
  outcome TEXT CHECK (outcome IN ('match','mismatch','no_answer')),
  cash_received_reported NUMERIC(12,2),   -- post-redeem confirmation (nullable)
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE model_scores (
  score_id BIGSERIAL PRIMARY KEY,
  subject_type TEXT CHECK (subject_type IN ('user','agent')), subject_id TEXT NOT NULL,
  model_name TEXT, model_version TEXT, score NUMERIC(6,5), top_reasons JSONB,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE cases (
  case_id BIGSERIAL PRIMARY KEY,
  mandate_id UUID REFERENCES mandates, agent_id TEXT REFERENCES agents,
  reason TEXT, evidence JSONB, status TEXT DEFAULT 'open' CHECK (status IN ('open','approved','denied','escalated')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE review_actions (
  action_id BIGSERIAL PRIMARY KEY,
  case_id BIGINT REFERENCES cases, reviewer TEXT NOT NULL, decision TEXT NOT NULL, note TEXT,
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE audit_log (
  log_id BIGSERIAL PRIMARY KEY,
  actor TEXT, action TEXT, entity TEXT, entity_id TEXT,
  policy_version TEXT, model_versions JSONB, detail JSONB,
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
