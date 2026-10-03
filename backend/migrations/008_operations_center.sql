-- Migration 008: multi-role operations center.
-- Staff accounts (supervisors, super admins), a call-management queue with automatic
-- retries and a manual supervisor queue, recorded customer responses, case assignment,
-- typed case notes and audit reports. Constraint changes only widen allowed values.

-- 1. Staff accounts. PINs are stored as salted PBKDF2 hashes, never in plain text.
CREATE TABLE staff (
  staff_id TEXT PRIMARY KEY CHECK (staff_id ~ '^[a-z][a-z0-9_]{2,40}$'),
  display_name TEXT NOT NULL CHECK (LENGTH(display_name) BETWEEN 2 AND 80),
  role TEXT NOT NULL CHECK (role IN ('supervisor','super_admin')),
  pin_hash TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

-- 2. Where a transaction check came from (a real agent or the live traffic simulator),
--    plus two new terminal states for the call-management flow.
ALTER TABLE txn_checks ADD COLUMN source TEXT NOT NULL DEFAULT 'agent'
  CHECK (source IN ('agent','simulator'));
ALTER TABLE txn_checks DROP CONSTRAINT IF EXISTS txn_checks_status_check;
ALTER TABLE txn_checks ADD CONSTRAINT txn_checks_status_check
  CHECK (status IN ('pending','calling','verified','suspicious','no_answer',
                    'manual_review','unreachable'));

ALTER TABLE voice_calls DROP CONSTRAINT IF EXISTS voice_calls_status_check;
ALTER TABLE voice_calls ADD CONSTRAINT voice_calls_status_check
  CHECK (status IN ('queued','ringing','in_progress','verified','mismatch','duress',
                    'no_answer','failed','completed','rejected','unclear'));

-- 3. One call task per transaction check. Automatic attempts are retried with a delay;
--    unclear answers and supervisor escalations go to the manual queue.
CREATE TABLE call_tasks (
  task_id BIGSERIAL PRIMARY KEY,
  check_id BIGINT NOT NULL UNIQUE REFERENCES txn_checks,
  user_id TEXT NOT NULL REFERENCES users,
  agent_id TEXT REFERENCES agents,
  status TEXT NOT NULL DEFAULT 'auto' CHECK (status IN (
    'auto','retry_scheduled','needs_manual','assigned','in_progress','resolved','ignored')),
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal','high','urgent')),
  auto_attempts INTEGER NOT NULL DEFAULT 0 CHECK (auto_attempts >= 0),
  manual_attempts INTEGER NOT NULL DEFAULT 0 CHECK (manual_attempts >= 0),
  next_attempt_at TIMESTAMPTZ,
  last_outcome TEXT,
  manual_reason TEXT CHECK (manual_reason IN (
    'unclear_response','retries_exhausted','admin_escalated','customer_callback')),
  assigned_to TEXT,
  assigned_by TEXT,
  assigned_at TIMESTAMPTZ,
  started_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT,
  resolution TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_call_tasks_due ON call_tasks (next_attempt_at)
  WHERE status = 'retry_scheduled';
CREATE INDEX ix_call_tasks_status ON call_tasks (status, created_at DESC);
CREATE INDEX ix_call_tasks_assignee ON call_tasks (assigned_to, status);

-- 4. Every customer answer is recorded as data: what was heard, how it was understood.
CREATE TABLE call_responses (
  response_id BIGSERIAL PRIMARY KEY,
  check_id BIGINT NOT NULL REFERENCES txn_checks,
  call_id UUID REFERENCES voice_calls,
  channel TEXT NOT NULL CHECK (channel IN ('ivr','manual')),
  raw_input TEXT,
  interpreted TEXT NOT NULL CHECK (interpreted IN (
    'amount','denied','duress','unclear','no_answer','callback','unreachable')),
  amount NUMERIC(12,2),
  confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  recorded_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_call_responses_check ON call_responses (check_id, created_at);

-- 5. Case assignment and work tracking.
ALTER TABLE cases ADD COLUMN assigned_to TEXT;
ALTER TABLE cases ADD COLUMN assigned_by TEXT;
ALTER TABLE cases ADD COLUMN assigned_at TIMESTAMPTZ;
ALTER TABLE cases ADD COLUMN closed_at TIMESTAMPTZ;
CREATE INDEX ix_cases_status ON cases (status, created_at DESC);
CREATE INDEX ix_cases_assignee ON cases (assigned_to, status);

CREATE TABLE case_notes (
  note_id BIGSERIAL PRIMARY KEY,
  case_id BIGINT NOT NULL REFERENCES cases,
  author TEXT NOT NULL,
  note_type TEXT NOT NULL CHECK (note_type IN ('message','critical','call_log','audit','system')),
  body TEXT NOT NULL CHECK (LENGTH(body) BETWEEN 1 AND 4000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_case_notes_case ON case_notes (case_id, created_at);

CREATE TABLE audit_reports (
  report_id BIGSERIAL PRIMARY KEY,
  case_id BIGINT NOT NULL REFERENCES cases,
  author TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('approved','denied','escalated')),
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high','critical')),
  customer_contacted BOOLEAN NOT NULL DEFAULT false,
  findings TEXT NOT NULL CHECK (LENGTH(findings) BETWEEN 10 AND 4000),
  action_taken TEXT NOT NULL CHECK (LENGTH(action_taken) BETWEEN 3 AND 2000),
  recommendation TEXT CHECK (recommendation IS NULL OR LENGTH(recommendation) <= 2000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_reports_case ON audit_reports (case_id, created_at DESC);

-- 6. Indexes for platform-scale admin listings (millions of users and transactions).
CREATE INDEX ix_transactions_ts ON transactions (ts DESC);
CREATE INDEX ix_audit_log_ts ON audit_log (ts DESC);
CREATE INDEX ix_txn_checks_created ON txn_checks (created_at DESC);
CREATE INDEX ix_voice_calls_status ON voice_calls (status, created_at);
