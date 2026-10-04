-- Migration 014: last result of each live AI model, so a restart serves it right away
-- while the models retrain in the background (pages never show "still training").
CREATE TABLE live_snapshots (
  name TEXT PRIMARY KEY CHECK (name IN ('agent_risk','outreach','liquidity','uplift')),
  payload JSONB NOT NULL,
  saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
