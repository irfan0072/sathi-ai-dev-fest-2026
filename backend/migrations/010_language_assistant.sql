-- Migration 010: customer language preference, customer assistant log, human hand-off.
-- Additive; constraint changes only widen allowed values.

-- 1. Language each customer prefers for calls and chat (bn, en, banglish).
--    'explicit' (customer chose it) is never overwritten by a learned guess.
CREATE TABLE customer_prefs (
  user_id TEXT PRIMARY KEY REFERENCES users,
  language TEXT NOT NULL CHECK (language IN ('bn','en','banglish')),
  source TEXT NOT NULL CHECK (source IN ('explicit','chat','speech','call_keypad','default')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Customer assistant conversation log. Text is stored after redaction only.
CREATE TABLE assistant_messages (
  message_id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('customer','agent','assistant')),
  language TEXT NOT NULL CHECK (language IN ('bn','en','banglish')),
  text TEXT NOT NULL CHECK (LENGTH(text) <= 2000),
  intent TEXT,
  guard TEXT,
  provider TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_assistant_messages_user ON assistant_messages (user_id, created_at DESC);

-- 3. Calls remember the language they used; customers can ask for a person.
ALTER TABLE voice_calls ADD COLUMN language TEXT NOT NULL DEFAULT 'bn'
  CHECK (language IN ('bn','en','banglish'));
ALTER TABLE voice_calls ADD COLUMN no_input_count INTEGER NOT NULL DEFAULT 0
  CHECK (no_input_count >= 0);
ALTER TABLE call_tasks DROP CONSTRAINT IF EXISTS call_tasks_manual_reason_check;
ALTER TABLE call_tasks ADD CONSTRAINT call_tasks_manual_reason_check CHECK (manual_reason IN (
  'unclear_response','retries_exhausted','admin_escalated','customer_callback',
  'customer_requested_human','assistant_report'));
ALTER TABLE call_responses DROP CONSTRAINT IF EXISTS call_responses_interpreted_check;
ALTER TABLE call_responses ADD CONSTRAINT call_responses_interpreted_check CHECK (interpreted IN (
  'amount','denied','duress','unclear','no_answer','callback','unreachable','no_input',
  'human_requested','language_switch'));
