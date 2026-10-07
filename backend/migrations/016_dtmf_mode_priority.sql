-- Migration 016: persisted input mode for confirmation calls (keypad-only fallback).
-- After unusable speech, a speech timeout or a speech-provider failure the next collection
-- step is DTMF-only. The mode lives in the database so a restart or a late callback cannot
-- re-enable speech, and so the safety limits are not reset.
ALTER TABLE voice_calls ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'speech_dtmf'
  CHECK (input_mode IN ('speech_dtmf','dtmf_only'));
ALTER TABLE voice_calls ADD COLUMN speech_unusable_count INTEGER NOT NULL DEFAULT 0
  CHECK (speech_unusable_count >= 0);
ALTER TABLE voice_calls ADD COLUMN input_mode_reason TEXT;
-- Explicit denial is its own recorded interpretation (it was "denied" before, but an empty
-- callback used to be read as denial; it is not any more).
