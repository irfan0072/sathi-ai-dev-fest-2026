-- Migration 005: runtime operational settings. Secrets are never stored here.
CREATE TABLE app_settings (
  key TEXT PRIMARY KEY CHECK (key ~ '^[a-z_]+\.[a-z0-9_]+$'),
  value JSONB NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
