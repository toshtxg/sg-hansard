-- =============================================================
-- Singapore Hansard — pipeline run log
-- Run this in Supabase SQL Editor (or via Claude Code's apply_migration)
--
-- One row per ingest run. Two reasons this table exists:
--
--   1. Observability. A run that fetches nothing and a run that ingests a
--      full sitting are both a green tick in the GitHub Actions UI. Between
--      2026-07-28 and 2026-08-11 the pipeline fetched zero Hansard while
--      reporting success daily, because upstream had switched to answering
--      non-sitting dates with HTTP 500 and every day was being counted as a
--      transient failure. Nothing in the database recorded that.
--
--   2. Activity. During recess the pipeline has nothing to write, so the
--      Supabase project sees almost no traffic and becomes a candidate for
--      free-tier auto-pause. A row per run is a small, honest heartbeat.
-- =============================================================

CREATE TABLE IF NOT EXISTS hansard_ingest_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_at         timestamptz NOT NULL,
  finished_at        timestamptz NOT NULL DEFAULT now(),
  script_version     text,
  git_sha            text,
  range_start        date,
  range_end          date,
  days_scanned       integer NOT NULL DEFAULT 0,
  sittings_ingested  integer NOT NULL DEFAULT 0,
  no_sitting_days    integer NOT NULL DEFAULT 0,
  transient_failures integer NOT NULL DEFAULT 0,
  hard_failures      integer NOT NULL DEFAULT 0,
  hard_failure_dates text[],
  total_blackout     boolean NOT NULL DEFAULT false,
  -- Latest sitting known at the start of the run. Lets you see how long the
  -- data has been static without joining back to hansard_sittings.
  latest_sitting     date
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_started_at
  ON hansard_ingest_runs (started_at DESC);

-- =============================================================
-- RLS — operational metadata, not parliamentary record. Unlike the content
-- tables there is no anon read policy and no GRANT to anon: only the service
-- role (which bypasses RLS) writes and reads it. Enabling RLS without a
-- policy is the point — it denies anon by default rather than by omission.
-- =============================================================
ALTER TABLE hansard_ingest_runs ENABLE ROW LEVEL SECURITY;
