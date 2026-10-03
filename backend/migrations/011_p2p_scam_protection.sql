-- Migration 011: person-to-person payments, scam-seller protection and community reports.
-- Additive only.

-- 1. Every wallet has a upay number (synthetic, derived from the customer ID namespace).
ALTER TABLE users ADD COLUMN msisdn TEXT;
UPDATE users SET msisdn = CASE
  WHEN user_id ~ '^U_9_[0-9]{7}$' THEN '019' || lpad(substring(user_id from 5), 8, '0')
  WHEN user_id ~ '^U_42_[0-9]{6}$' THEN '01742' || substring(user_id from 6)
  WHEN user_id ~ '^U_4242_[0-9]{6}$' THEN '01842' || substring(user_id from 8)
  WHEN user_id ~ '^U_2026_[0-9]{6}$' THEN '01626' || substring(user_id from 8)
  WHEN user_id ~ '^U_777_[0-9]{6}$' THEN '01577' || substring(user_id from 7)
  END;
CREATE UNIQUE INDEX uq_users_msisdn ON users (msisdn) WHERE msisdn IS NOT NULL;

-- 2. Person-to-person transfers (send money). Each side also gets a ledger row.
CREATE TABLE p2p_transfers (
  transfer_id BIGSERIAL PRIMARY KEY,
  sender_id TEXT NOT NULL REFERENCES users,
  receiver_id TEXT NOT NULL REFERENCES users,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  sender_txn_id BIGINT REFERENCES transactions,
  receiver_txn_id BIGINT REFERENCES transactions,
  reference TEXT CHECK (reference IS NULL OR LENGTH(reference) <= 80),
  warning_level TEXT CHECK (warning_level IN ('none','caution','high')),
  warning_acknowledged BOOLEAN NOT NULL DEFAULT false,
  source TEXT NOT NULL DEFAULT 'app' CHECK (source IN ('app','simulator','seed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (sender_id <> receiver_id)
);
CREATE INDEX ix_p2p_receiver_time ON p2p_transfers (receiver_id, created_at DESC);
CREATE INDEX ix_p2p_sender_time ON p2p_transfers (sender_id, created_at DESC);
CREATE INDEX ix_p2p_time ON p2p_transfers (created_at DESC);

-- 3. Receiver risk: personal accounts that look like unregistered shops or scam sellers.
CREATE TABLE receiver_flags (
  user_id TEXT PRIMARY KEY REFERENCES users,
  score NUMERIC(5,4) NOT NULL CHECK (score >= 0 AND score <= 1),
  level TEXT NOT NULL CHECK (level IN ('watch','caution','high')),
  reasons JSONB NOT NULL,
  features JSONB NOT NULL,
  case_id BIGINT REFERENCES cases,
  first_flagged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Anonymous community scam reports. The reporter is stored only as a keyed hash, so
--    moderators cannot see who reported, but duplicates and abuse can still be stopped.
CREATE TABLE community_reports (
  report_id BIGSERIAL PRIMARY KEY,
  identifier_type TEXT NOT NULL CHECK (identifier_type IN (
    'upay_number','facebook','instagram','whatsapp','telegram','website','other')),
  identifier_norm TEXT NOT NULL CHECK (LENGTH(identifier_norm) BETWEEN 3 AND 120),
  identifier_display TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN (
    'not_delivered','fake_product','advance_fee','impersonation','investment','job_offer',
    'other')),
  amount_lost NUMERIC(12,2) CHECK (amount_lost IS NULL OR amount_lost >= 0),
  incident_date DATE,
  description TEXT NOT NULL CHECK (LENGTH(description) BETWEEN 10 AND 1000),
  reporter_hash TEXT NOT NULL CHECK (LENGTH(reporter_hash) = 64),
  paid_via_upay BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN (
    'published','verified','rejected','hidden')),
  moderated_by TEXT,
  moderated_at TIMESTAMPTZ,
  moderation_note TEXT,
  me_too_count INTEGER NOT NULL DEFAULT 0 CHECK (me_too_count >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (identifier_norm, reporter_hash)
);
CREATE INDEX ix_community_identifier ON community_reports (identifier_norm, status);
CREATE INDEX ix_community_recent ON community_reports (created_at DESC);

CREATE TABLE community_votes (
  report_id BIGINT NOT NULL REFERENCES community_reports,
  voter_hash TEXT NOT NULL CHECK (LENGTH(voter_hash) = 64),
  kind TEXT NOT NULL CHECK (kind IN ('me_too','helpful','abuse')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, voter_hash, kind)
);
