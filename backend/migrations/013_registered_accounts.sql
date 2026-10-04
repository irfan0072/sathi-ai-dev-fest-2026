-- Migration 013: real test accounts created by a super admin.
-- A registered customer or agent signs in with their own phone number and a PIN. Calls and
-- SMS for a registered customer go to that number. Synthetic numbers are never dialled.
-- Internal IDs: U_P_<number> for customers, A_P_<number> for agents.

CREATE TABLE registered_accounts (
  account_id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('customer','agent')),
  msisdn TEXT NOT NULL CHECK (msisdn ~ '^01[3-9][0-9]{8}$'),
  user_id TEXT UNIQUE REFERENCES users,
  agent_id TEXT UNIQUE REFERENCES agents,
  display_name TEXT NOT NULL CHECK (LENGTH(display_name) BETWEEN 2 AND 80),
  pin_hash TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ,
  UNIQUE (kind, msisdn),
  CHECK ((kind = 'customer') = (user_id IS NOT NULL)),
  CHECK ((kind = 'agent') = (agent_id IS NOT NULL))
);
