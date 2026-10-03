-- Migration 009: indexes on foreign keys that point at transactions, so deletes and
-- integrity checks stay fast with millions of ledger rows. Additive only.
CREATE INDEX IF NOT EXISTS ix_sessions_txn ON sessions (txn_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_ts ON sessions (user_id, ts);
CREATE INDEX IF NOT EXISTS ix_mandates_redeemed_txn ON mandates (redeemed_txn_id);
