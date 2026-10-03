-- Migration 006: provider credentials entered from the Settings page.
-- Values are Fernet-encrypted with a key that exists only in the server environment
-- (SATHI_SECRETS_KEY). Plaintext never reaches the database or the browser.
CREATE TABLE provider_credentials (
  name TEXT PRIMARY KEY CHECK (name ~ '^[A-Z][A-Z0-9_]{2,63}$'),
  ciphertext TEXT NOT NULL,
  hint TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
