-- Migration 004: customer notifications, analyst watchlist and voice provider widening.
-- Additive except the voice_calls provider check, which is widened (never narrowed).

-- 1. Outbound customer notifications (SMS). Phone numbers are stored masked only.
CREATE TABLE notifications (
  notification_id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users,
  mandate_id UUID REFERENCES mandates,
  channel TEXT NOT NULL CHECK (channel IN ('sms')),
  provider TEXT NOT NULL,
  template TEXT NOT NULL,
  to_masked TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sent','simulated','failed','skipped')),
  provider_ref TEXT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_notifications_user ON notifications (user_id, created_at DESC);
CREATE UNIQUE INDEX uq_notifications_once ON notifications (mandate_id, template)
  WHERE mandate_id IS NOT NULL;

-- 2. Analyst-controlled enhanced-verification watchlist. It never blocks cash-out;
--    it forces the stronger verification channel for the agent's mandates.
CREATE TABLE agent_watchlist (
  agent_id TEXT PRIMARY KEY REFERENCES agents,
  reason TEXT NOT NULL CHECK (LENGTH(reason) BETWEEN 3 AND 500),
  added_by TEXT NOT NULL,
  case_id BIGINT REFERENCES cases,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Allow the vendor-neutral Bangladesh HTTP IVR provider.
ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS voice_calls_provider_check;
ALTER TABLE voice_calls ADD CONSTRAINT voice_calls_provider_check
  CHECK (provider IN ('twilio','simulated','bd_http_ivr'));
