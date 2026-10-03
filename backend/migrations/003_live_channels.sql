-- Migration 003: live verification channel, real-time mandate risk and AI case briefs.
-- Additive only: no existing table, row or constraint is changed.

-- 1. Outbound verification calls. The phone number is never stored; only a masked form.
CREATE TABLE voice_calls (
  call_id UUID PRIMARY KEY,
  mandate_id UUID NOT NULL REFERENCES mandates,
  user_id TEXT NOT NULL REFERENCES users,
  provider TEXT NOT NULL CHECK (provider IN ('twilio','simulated')),
  provider_call_sid TEXT,
  to_masked TEXT NOT NULL,
  token_hash TEXT NOT NULL CHECK (LENGTH(token_hash) = 64),
  status TEXT NOT NULL CHECK (status IN (
    'queued','ringing','in_progress','verified','mismatch','duress',
    'no_answer','failed','completed','rejected'
  )),
  digit_attempts INTEGER NOT NULL DEFAULT 0 CHECK (digit_attempts >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_voice_calls_mandate ON voice_calls (mandate_id, created_at DESC);
CREATE UNIQUE INDEX uq_voice_calls_live_mandate ON voice_calls (mandate_id)
  WHERE status IN ('queued','ringing','in_progress');

-- 2. Real-time risk assessment captured at mandate request. Risk only steps up verification.
CREATE TABLE mandate_risk (
  mandate_id UUID PRIMARY KEY REFERENCES mandates,
  score NUMERIC(5,4) NOT NULL CHECK (score >= 0 AND score <= 1),
  band TEXT NOT NULL CHECK (band IN ('low','medium','high')),
  step_up TEXT NOT NULL CHECK (step_up IN ('keypad_or_call','call_required','call_and_review')),
  reasons JSONB NOT NULL,
  engine_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Generated analyst briefs, stored with provider provenance. Never a decision.
CREATE TABLE case_briefs (
  brief_id BIGSERIAL PRIMARY KEY,
  case_id BIGINT NOT NULL REFERENCES cases,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  brief JSONB NOT NULL,
  evidence_sha256 TEXT NOT NULL CHECK (LENGTH(evidence_sha256) = 64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_case_briefs_case ON case_briefs (case_id, created_at DESC);
