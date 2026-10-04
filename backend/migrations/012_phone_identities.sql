-- Migration 012: phone numbers as the visible identity for customers and agents.
-- Additive only. Internal user_id / agent_id keys stay unchanged (models, config and
-- foreign keys depend on them); screens show and accept the phone number instead.

-- 1. Deterministic synthetic numbers derived from each ID namespace.
--    Customers: 015/016/017/018/019 ranges (same mapping as migration 011).
--    Agents: the 013 range, so a customer and an agent never share a number.
CREATE OR REPLACE FUNCTION sathi_user_msisdn(uid TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN uid ~ '^U_9_[0-9]{7}$' THEN '019' || lpad(substring(uid from 5), 8, '0')
    WHEN uid ~ '^U_42_[0-9]{6}$' THEN '01742' || substring(uid from 6)
    WHEN uid ~ '^U_4242_[0-9]{6}$' THEN '01842' || substring(uid from 8)
    WHEN uid ~ '^U_2026_[0-9]{6}$' THEN '01626' || substring(uid from 8)
    WHEN uid ~ '^U_777_[0-9]{6}$' THEN '01577' || substring(uid from 7)
  END
$$;

CREATE OR REPLACE FUNCTION sathi_agent_msisdn(aid TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN aid ~ '^A_9_[0-9]{6}$' THEN '0139' || lpad(substring(aid from 5), 7, '0')
    WHEN aid ~ '^A_777_[0-9]{6}$' THEN '01377' || substring(aid from 7)
    WHEN aid ~ '^A_[0-9]{6}$' THEN '01310' || substring(aid from 3)
  END
$$;

-- 2. Customers seeded after migration 011 have no number yet.
UPDATE users SET msisdn = sathi_user_msisdn(user_id) WHERE msisdn IS NULL;

-- 3. Agents get a wallet number too.
ALTER TABLE agents ADD COLUMN msisdn TEXT;
UPDATE agents SET msisdn = sathi_agent_msisdn(agent_id);
CREATE UNIQUE INDEX uq_agents_msisdn ON agents (msisdn) WHERE msisdn IS NOT NULL;

-- 4. New rows get their number automatically.
CREATE OR REPLACE FUNCTION sathi_fill_user_msisdn() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.msisdn IS NULL THEN NEW.msisdn := sathi_user_msisdn(NEW.user_id); END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_users_msisdn BEFORE INSERT ON users
  FOR EACH ROW EXECUTE FUNCTION sathi_fill_user_msisdn();

CREATE OR REPLACE FUNCTION sathi_fill_agent_msisdn() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.msisdn IS NULL THEN NEW.msisdn := sathi_agent_msisdn(NEW.agent_id); END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_agents_msisdn BEFORE INSERT ON agents
  FOR EACH ROW EXECUTE FUNCTION sathi_fill_agent_msisdn();
