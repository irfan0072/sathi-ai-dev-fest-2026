-- Migration 002: Durable mandates, nullability clarification, attempt counters, and uniqueness constraints.
-- Preserves existing tables, data, and checksums. Duplicate conflicts abort migration rather than deleting data.

-- 1. Check for duplicate live mandates for the same user before creating unique index
DO $$
BEGIN
  IF EXISTS (
    SELECT user_id FROM mandates
    WHERE status IN ('requested', 'verified', 'active')
    GROUP BY user_id HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'Duplicate live mandate found for user; aborting migration to preserve data integrity';
  END IF;
END $$;

-- 2. Check for duplicate cash confirmation events per mandate before creating unique index
DO $$
BEGIN
  IF EXISTS (
    SELECT mandate_id FROM verification_events
    WHERE cash_received_reported IS NOT NULL
    GROUP BY mandate_id HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'Duplicate cash-confirmation event found for mandate; aborting migration to preserve data integrity';
  END IF;
END $$;

-- 3. Modify code_hash column on mandates: allow NULL for unissued states
ALTER TABLE mandates ALTER COLUMN code_hash DROP NOT NULL;

-- 4. Check constraint: any non-NULL code_hash must be exactly 64 hex characters
ALTER TABLE mandates ADD CONSTRAINT chk_mandates_code_hash_hex
  CHECK (code_hash IS NULL OR (LENGTH(code_hash) = 64 AND code_hash ~ '^[0-9a-fA-F]{64}$'));

-- 5. Check constraint: active and redeemed states strictly require a 64-character hash
ALTER TABLE mandates ADD CONSTRAINT chk_mandates_active_redeemed_hash
  CHECK (status NOT IN ('active', 'redeemed') OR (code_hash IS NOT NULL AND LENGTH(code_hash) = 64 AND code_hash ~ '^[0-9a-fA-F]{64}$'));

-- 6. Add nonnegative attempt counters with default 0
ALTER TABLE mandates ADD COLUMN verification_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mandates ADD CONSTRAINT chk_mandates_nonnegative_verification_attempts
  CHECK (verification_attempts >= 0);

ALTER TABLE mandates ADD COLUMN redemption_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mandates ADD CONSTRAINT chk_mandates_nonnegative_redemption_attempts
  CHECK (redemption_attempts >= 0);

-- 7. Unique partial index on user_id for live statuses ('requested', 'verified', 'active')
CREATE UNIQUE INDEX uq_mandates_live_user ON mandates (user_id)
  WHERE status IN ('requested', 'verified', 'active');

-- 8. Unique partial index for cash-confirmation event per mandate
CREATE UNIQUE INDEX uq_verification_events_cash_confirmation ON verification_events (mandate_id)
  WHERE cash_received_reported IS NOT NULL;
