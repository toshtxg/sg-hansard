-- =============================================================
-- Singapore Hansard — statement timeout for the ingest writer
-- Run this in Supabase SQL Editor (or via Claude Code's apply_migration)
--
-- The ingest writes through PostgREST with the service_role key. service_role
-- has no statement_timeout of its own, so it inherits the 8s set on
-- `authenticator` — a limit sized for interactive dashboard reads.
--
-- hansard_speeches carries four pg_trgm GIN indexes (speech_details,
-- one_liner, discussion_title, mp_name_fuzzy_matched). GIN fastupdate buffers
-- new entries in a pending list and the insert that pushes a list past
-- gin_pending_list_limit (4MB) merges it into the main index inline. Each
-- merge costs ~3s on the current index sizes, so a 300-row speeches batch
-- that trips two or more of them runs past 8s, is cancelled (57014), rolls
-- the merge back, and every retry hits the same wall. That failed the
-- 2026-10-06 sitting on 2026-10-14 with pending lists of 406 / 318 pages.
--
-- Give the backend writer headroom well above the worst case (four full
-- merges plus the batch itself). anon/authenticated keep their short limits.
-- =============================================================

ALTER ROLE service_role SET statement_timeout = '60s';

-- PostgREST caches per-role settings with the schema cache.
NOTIFY pgrst, 'reload schema';
