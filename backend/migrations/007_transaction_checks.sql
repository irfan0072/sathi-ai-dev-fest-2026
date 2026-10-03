-- Migration 007: confirm completed cash-outs with the customer afterwards.
-- An agent records a cash-out; the system then calls the customer, who types the cash they
-- received. A match marks the transaction verified; anything else is flagged suspicious for a
-- human supervisor. The AI only recommends; it never labels anything as fraud.

CREATE TABLE txn_checks (
  check_id BIGSERIAL PRIMARY KEY,
  txn_id BIGINT NOT NULL UNIQUE REFERENCES transactions,
  user_id TEXT NOT NULL REFERENCES users,
  agent_id TEXT REFERENCES agents,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  status TEXT NOT NULL CHECK (status IN ('pending','calling','verified','suspicious','no_answer')),
  outcome TEXT CHECK (outcome IN ('match','mismatch','denied','duress')),
  stated_amount NUMERIC(12,2),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  recommendation JSONB,
  case_id BIGINT REFERENCES cases,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_txn_checks_status ON txn_checks (status, created_at DESC);
CREATE INDEX ix_txn_checks_user ON txn_checks (user_id, created_at DESC);
CREATE INDEX ix_txn_checks_agent ON txn_checks (agent_id, created_at DESC);

-- Calls can now belong to a mandate (old flow) or to a transaction check (new flow).
ALTER TABLE voice_calls ALTER COLUMN mandate_id DROP NOT NULL;
ALTER TABLE voice_calls ADD COLUMN check_id BIGINT REFERENCES txn_checks;
ALTER TABLE voice_calls ADD CONSTRAINT chk_voice_calls_one_target
  CHECK ((mandate_id IS NULL) <> (check_id IS NULL));
CREATE UNIQUE INDEX uq_voice_calls_live_check ON voice_calls (check_id)
  WHERE status IN ('queued','ringing','in_progress');
