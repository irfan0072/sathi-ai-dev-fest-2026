-- Migration 015: provider-failure recovery and the safe independent follow-up status.
-- Additive only: it widens allowed values and adds nullable or defaulted columns.

-- 1. A committed check whose first call could not be placed is retried a bounded number of
--    times and then handed to a person; these columns make the failure visible and auditable.
ALTER TABLE call_tasks ADD COLUMN placement_failures INTEGER NOT NULL DEFAULT 0
  CHECK (placement_failures >= 0);
ALTER TABLE call_tasks ADD COLUMN last_placement_error TEXT;
ALTER TABLE call_tasks DROP CONSTRAINT IF EXISTS call_tasks_manual_reason_check;
ALTER TABLE call_tasks ADD CONSTRAINT call_tasks_manual_reason_check CHECK (manual_reason IN (
  'unclear_response','retries_exhausted','admin_escalated','customer_callback',
  'customer_requested_human','assistant_report','provider_failure'));

-- 2. Independent customer contact. Calling the same handset again does not prove that the
--    customer is not under pressure, so a suspicious check needs a separate follow-up before
--    a case can be cleared. 'uncertain' stays unresolved.
ALTER TABLE call_tasks ADD COLUMN followup_status TEXT NOT NULL DEFAULT 'not_required'
  CHECK (followup_status IN ('not_required','required','attempted','reached_independently',
                             'uncertain','unreachable'));
ALTER TABLE call_tasks ADD COLUMN followup_channel TEXT
  CHECK (followup_channel IS NULL OR followup_channel IN ('registered_number','in_person'));
ALTER TABLE call_tasks ADD COLUMN followup_assigned_to TEXT;
ALTER TABLE call_tasks ADD COLUMN followup_attempts INTEGER NOT NULL DEFAULT 0
  CHECK (followup_attempts >= 0);
ALTER TABLE call_tasks ADD COLUMN followup_updated_by TEXT;
ALTER TABLE call_tasks ADD COLUMN followup_updated_at TIMESTAMPTZ;
CREATE INDEX ix_call_tasks_followup ON call_tasks (followup_status, task_id)
  WHERE followup_status IN ('required','attempted','uncertain','unreachable');
-- Existing suspicious checks created before this migration need the same follow-up.
UPDATE call_tasks t SET followup_status = 'required'
  FROM txn_checks c WHERE c.check_id = t.check_id AND c.status = 'suspicious';

-- 3. Append-only audit trail. Application code only ever INSERTs into audit_log; these
--    triggers make an UPDATE, DELETE or TRUNCATE fail at the database. This is a durable,
--    append-only trail, NOT proof against a database owner or superuser, who can drop the
--    trigger. A cryptographic hash chain and an INSERT-only runtime role are not implemented.
CREATE FUNCTION audit_log_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_reject_mutation();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_mutation();
