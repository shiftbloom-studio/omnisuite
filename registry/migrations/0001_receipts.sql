-- One row per listed receipt. Fingerprints and marks only: no audio, no text,
-- and nothing about the person who signed the mandate.
CREATE TABLE receipts (
  id TEXT PRIMARY KEY,               -- the receipt id the file carries in its manifest
  voice TEXT NOT NULL,               -- SHA-256 of the voice's reference clip
  mandate TEXT NOT NULL,             -- id of the stem mandate that let this listing through
  listed_at INTEGER NOT NULL,        -- unix seconds, set by the registry
  created TEXT NOT NULL,             -- when the install says it made the file
  model TEXT NOT NULL,
  audio_sha256 TEXT NOT NULL,
  seconds REAL NOT NULL,
  sample_rate INTEGER NOT NULL,
  watermark_scheme TEXT NOT NULL,
  watermark_tag TEXT NOT NULL,
  signer_name TEXT NOT NULL,
  signer_serial TEXT NOT NULL,
  enrolment TEXT
);
-- Not unique: anyone with a mandate can claim a fingerprint, so a claim must never block the real one.
CREATE INDEX receipts_audio ON receipts (audio_sha256);
-- For the ceiling on what one mandate may list per day.
CREATE INDEX receipts_mandate ON receipts (mandate, listed_at);
