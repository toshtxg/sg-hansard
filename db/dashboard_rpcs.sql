-- =============================================================
-- Singapore Hansard Dashboard — RPCs & Indexes
-- Run this in Supabase SQL Editor (or via Claude Code's apply_migration)
-- =============================================================

-- Enable trigram extension for topic search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================
-- INDEXES
-- =============================================================
CREATE INDEX IF NOT EXISTS idx_speeches_mp_name ON hansard_speeches (mp_name_fuzzy_matched);
CREATE INDEX IF NOT EXISTS idx_speeches_sitting_date ON hansard_speeches (sitting_date);
CREATE INDEX IF NOT EXISTS idx_speeches_section_type ON hansard_speeches (section_type);
CREATE INDEX IF NOT EXISTS idx_speeches_mp_date ON hansard_speeches (mp_name_fuzzy_matched, sitting_date);
CREATE INDEX IF NOT EXISTS idx_speeches_discussion_title_trgm ON hansard_speeches USING gin (discussion_title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_speeches_one_liner_trgm ON hansard_speeches USING gin (one_liner gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_speeches_mp_name_trgm ON hansard_speeches USING gin (mp_name_fuzzy_matched gin_trgm_ops);

-- =============================================================
-- OVERVIEW RPCs
-- =============================================================

CREATE OR REPLACE FUNCTION overview_stats()
RETURNS json AS $$
  SELECT json_build_object(
    'total_speeches', (SELECT COUNT(*) FROM hansard_speeches),
    'total_sittings', (SELECT COUNT(*) FROM hansard_sittings),
    'total_speakers', (SELECT COUNT(DISTINCT mp_name_fuzzy_matched) FROM hansard_speeches WHERE mp_name_fuzzy_matched IS NOT NULL),
    'total_words', (SELECT SUM(word_count) FROM hansard_speeches),
    'earliest_sitting', (SELECT MIN(sitting_date) FROM hansard_sittings),
    'latest_sitting', (SELECT MAX(sitting_date) FROM hansard_sittings)
  );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION recent_sittings(p_limit int DEFAULT 10)
RETURNS json AS $$
  SELECT json_agg(r) FROM (
    SELECT s.sitting_date, s.source_url,
      COUNT(sp.row_num) as speech_count,
      COALESCE(SUM(sp.word_count), 0) as word_count,
      ai.summary_3_sentences
    FROM hansard_sittings s
    LEFT JOIN hansard_speeches sp ON s.sitting_date = sp.sitting_date
    LEFT JOIN hansard_ai_summaries ai ON s.sitting_date = ai.sitting_date
    GROUP BY s.sitting_date, s.source_url, ai.summary_3_sentences
    ORDER BY s.sitting_date DESC
    LIMIT p_limit
  ) r;
$$ LANGUAGE sql STABLE;

-- =============================================================
-- MP PROFILE RPCs
-- =============================================================

CREATE OR REPLACE FUNCTION mp_list()
RETURNS json AS $$
  SELECT json_agg(r ORDER BY total_words DESC) FROM (
    SELECT 
      mp_name_fuzzy_matched as mp_name,
      SUM(word_count) as total_words,
      COUNT(*) as total_speeches,
      COUNT(DISTINCT sitting_date) as sittings_active,
      MODE() WITHIN GROUP (ORDER BY section_type) as primary_section_type
    FROM hansard_speeches
    WHERE mp_name_fuzzy_matched IS NOT NULL
    GROUP BY mp_name_fuzzy_matched
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION mp_summary(p_mp_name text)
RETURNS json AS $$
  SELECT json_build_object(
    'mp_name', p_mp_name,
    'total_words', SUM(word_count),
    'total_speeches', COUNT(*),
    'sittings_active', COUNT(DISTINCT sitting_date),
    'first_sitting', MIN(sitting_date),
    'last_sitting', MAX(sitting_date),
    'parliaments', array_agg(DISTINCT parliament_no ORDER BY parliament_no)
  )
  FROM hansard_speeches
  WHERE mp_name_fuzzy_matched = p_mp_name;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION mp_activity_over_time(p_mp_name text, p_granularity text DEFAULT 'quarter')
RETURNS json AS $$
  SELECT json_agg(r ORDER BY period) FROM (
    SELECT 
      CASE WHEN p_granularity = 'year' 
        THEN date_trunc('year', sitting_date)::date::text
        ELSE date_trunc('quarter', sitting_date)::date::text
      END as period,
      SUM(word_count) as word_count,
      COUNT(*) as speech_count
    FROM hansard_speeches
    WHERE mp_name_fuzzy_matched = p_mp_name
    GROUP BY period
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION mp_top_topics(p_mp_name text, p_limit int DEFAULT 20, p_section_type text DEFAULT NULL)
RETURNS json AS $$
  SELECT json_agg(r) FROM (
    SELECT 
      discussion_title,
      SUM(word_count) as word_count,
      COUNT(*) as speech_count,
      MODE() WITHIN GROUP (ORDER BY section_type) as section_type
    FROM hansard_speeches
    WHERE mp_name_fuzzy_matched = p_mp_name
      AND discussion_title IS NOT NULL
      AND (p_section_type IS NULL OR section_type = p_section_type)
    GROUP BY discussion_title
    ORDER BY word_count DESC
    LIMIT p_limit
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION mp_section_breakdown(p_mp_name text)
RETURNS json AS $$
  SELECT json_agg(r ORDER BY word_count DESC) FROM (
    SELECT section_type, COUNT(*) as speech_count, SUM(word_count) as word_count
    FROM hansard_speeches
    WHERE mp_name_fuzzy_matched = p_mp_name
    GROUP BY section_type
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION mp_recent_speeches(p_mp_name text, p_limit int DEFAULT 20, p_offset int DEFAULT 0)
RETURNS json AS $$
  SELECT json_agg(r) FROM (
    SELECT 
      sp.sitting_date, sp.discussion_title, sp.section_type, 
      sp.word_count, sp.one_liner,
      s.source_url
    FROM hansard_speeches sp
    JOIN hansard_sittings s ON sp.sitting_date = s.sitting_date
    WHERE sp.mp_name_fuzzy_matched = p_mp_name
    ORDER BY sp.sitting_date DESC, sp.row_num
    LIMIT p_limit OFFSET p_offset
  ) r;
$$ LANGUAGE sql STABLE;

-- =============================================================
-- TOPIC EXPLORER RPCs
-- =============================================================

CREATE OR REPLACE FUNCTION search_topics(
  p_query text DEFAULT NULL,
  p_date_from date DEFAULT NULL,
  p_date_to date DEFAULT NULL,
  p_section_types text[] DEFAULT NULL,
  p_parliament_no int DEFAULT NULL,
  p_limit int DEFAULT 50,
  p_offset int DEFAULT 0
)
RETURNS json AS $$
  SELECT json_agg(r) FROM (
    SELECT 
      discussion_title,
      sitting_date,
      MODE() WITHIN GROUP (ORDER BY section_type) as section_type,
      COUNT(DISTINCT mp_name_fuzzy_matched) as speaker_count,
      SUM(word_count) as total_words,
      MAX(parliament_no) as parliament_no
    FROM hansard_speeches
    WHERE discussion_title IS NOT NULL
      AND (p_query IS NULL
        OR discussion_title ILIKE '%' || p_query || '%'
        OR one_liner ILIKE '%' || p_query || '%'
        OR mp_name_fuzzy_matched ILIKE '%' || p_query || '%'
        OR themes::text ILIKE '%' || p_query || '%'
      )
      AND (p_date_from IS NULL OR sitting_date >= p_date_from)
      AND (p_date_to IS NULL OR sitting_date <= p_date_to)
      AND (p_section_types IS NULL OR section_type = ANY(p_section_types))
      AND (p_parliament_no IS NULL OR parliament_no = p_parliament_no)
    GROUP BY discussion_title, sitting_date
    ORDER BY sitting_date DESC
    LIMIT p_limit OFFSET p_offset
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION topic_detail(p_discussion_title text, p_sitting_date date)
RETURNS json AS $$
  SELECT json_build_object(
    'discussion_title', p_discussion_title,
    'sitting_date', p_sitting_date,
    'source_url', (SELECT source_url FROM hansard_sittings WHERE sitting_date = p_sitting_date),
    'speakers', (
      SELECT json_agg(json_build_object(
        'mp_name', mp_name_fuzzy_matched,
        'word_count', word_count,
        'one_liner', one_liner,
        'themes', themes,
        'section_type', section_type
      ) ORDER BY row_num)
      FROM hansard_speeches
      WHERE discussion_title = p_discussion_title AND sitting_date = p_sitting_date
    )
  );
$$ LANGUAGE sql STABLE;

-- =============================================================
-- TRENDS RPCs
-- =============================================================

CREATE OR REPLACE FUNCTION trends_volume_over_time(p_granularity text DEFAULT 'quarter', p_section_type text DEFAULT NULL)
RETURNS json AS $$
  SELECT json_agg(r ORDER BY period, section_type) FROM (
    SELECT 
      CASE WHEN p_granularity = 'year' 
        THEN date_trunc('year', sitting_date)::date::text
        ELSE date_trunc('quarter', sitting_date)::date::text
      END as period,
      section_type,
      COUNT(*) as speech_count,
      SUM(word_count) as word_count
    FROM hansard_speeches
    WHERE (p_section_type IS NULL OR section_type = p_section_type)
    GROUP BY period, section_type
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION trends_parliament_summary()
RETURNS json AS $$
  SELECT json_agg(r ORDER BY parliament_no) FROM (
    SELECT 
      parliament_no,
      MIN(sitting_date)::text || ' to ' || MAX(sitting_date)::text as date_range,
      COUNT(DISTINCT sitting_date) as total_sittings,
      COUNT(*) as total_speeches,
      COUNT(DISTINCT mp_name_fuzzy_matched) as total_speakers,
      ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT sitting_date), 0), 1) as avg_speeches_per_sitting
    FROM hansard_speeches
    WHERE parliament_no IS NOT NULL
    GROUP BY parliament_no
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION trends_sitting_intensity(p_granularity text DEFAULT 'year')
RETURNS json AS $$
  SELECT json_agg(r ORDER BY period) FROM (
    SELECT 
      CASE WHEN p_granularity = 'year' 
        THEN date_trunc('year', s.sitting_date)::date::text
        ELSE date_trunc('quarter', s.sitting_date)::date::text
      END as period,
      COUNT(DISTINCT s.sitting_date) as sitting_count,
      ROUND(COALESCE(SUM(sp.word_count), 0)::numeric / NULLIF(COUNT(DISTINCT s.sitting_date), 0), 0) as avg_words_per_sitting
    FROM hansard_sittings s
    LEFT JOIN hansard_speeches sp ON s.sitting_date = sp.sitting_date
    GROUP BY period
  ) r;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION trends_speaker_diversity(p_granularity text DEFAULT 'year')
RETURNS json AS $$
  SELECT json_agg(r ORDER BY period) FROM (
    SELECT
      CASE WHEN p_granularity = 'year'
        THEN date_trunc('year', sitting_date)::date::text
        ELSE date_trunc('quarter', sitting_date)::date::text
      END as period,
      COUNT(DISTINCT mp_name_fuzzy_matched) as unique_speakers,
      ROUND(SUM(word_count)::numeric / NULLIF(COUNT(DISTINCT mp_name_fuzzy_matched), 0), 0) as avg_words_per_speaker
    FROM hansard_speeches
    WHERE mp_name_fuzzy_matched IS NOT NULL
    GROUP BY period
  ) r;
$$ LANGUAGE sql STABLE;

-- =============================================================
-- 2026 ADDITIONS: sitting detail, MP attendance, AI summaries
-- (Appended section — apply this whole file in Supabase SQL Editor.)
-- =============================================================

-- Supporting indexes for the new attendance / PTBA lookups.
-- (hansard_ai_summaries.sitting_date is already covered by its PK, so no index there.)
CREATE INDEX IF NOT EXISTS idx_attendance_mp_name_cleaned ON hansard_attendance (mp_name_cleaned);
CREATE INDEX IF NOT EXISTS idx_ptba_mp_name_cleaned ON hansard_ptba (mp_name_cleaned);

-- Full detail for a single sitting: metadata + AI summary + attendance + speeches.
CREATE OR REPLACE FUNCTION sitting_detail(p_sitting_date date)
RETURNS json AS $$
  SELECT json_build_object(
    'sitting_date', p_sitting_date,
    'source_url', (SELECT source_url FROM hansard_sittings WHERE sitting_date = p_sitting_date),
    'summary_3_sentences', (
      SELECT summary_3_sentences FROM hansard_ai_summaries WHERE sitting_date = p_sitting_date
    ),
    'attendance', (
      SELECT json_build_object(
        'present_count', COUNT(*) FILTER (WHERE dim_is_present),
        'absent_count', COUNT(*) FILTER (WHERE NOT dim_is_present),
        'total', COUNT(*),
        'absent', COALESCE(
          (SELECT json_agg(mp_name_cleaned ORDER BY mp_name_cleaned)
           FROM hansard_attendance
           WHERE sitting_date = p_sitting_date AND NOT dim_is_present),
          '[]'::json
        ),
        'ptba', COALESCE(
          (SELECT json_agg(json_build_object(
              'mp_name_cleaned', mp_name_cleaned,
              'ptba_from', ptba_from,
              'ptba_to', ptba_to
            ) ORDER BY mp_name_cleaned)
           FROM hansard_ptba
           WHERE sitting_date = p_sitting_date),
          '[]'::json
        )
      )
      FROM hansard_attendance
      WHERE sitting_date = p_sitting_date
    ),
    'speeches', COALESCE(
      (SELECT json_agg(json_build_object(
          'row_num', row_num,
          'discussion_title', discussion_title,
          'section_type', section_type,
          'mp_name', COALESCE(mp_name_fuzzy_matched, mp_name_raw),
          'word_count', word_count,
          'one_liner', one_liner
        ) ORDER BY row_num)
       FROM hansard_speeches
       WHERE sitting_date = p_sitting_date),
      '[]'::json
    )
  );
$$ LANGUAGE sql STABLE;

-- Attendance summary for a single MP (joined on the cleaned attendance name).
-- attendance_rate is returned as a 0-1 fraction rounded to 3 dp.
CREATE OR REPLACE FUNCTION mp_attendance(p_mp_name text)
RETURNS json AS $$
  SELECT json_build_object(
    'mp_name', p_mp_name,
    'sittings_total', (
      SELECT COUNT(*) FROM hansard_attendance WHERE mp_name_cleaned = p_mp_name
    ),
    'sittings_present', (
      SELECT COUNT(*) FROM hansard_attendance
      WHERE mp_name_cleaned = p_mp_name AND dim_is_present
    ),
    'attendance_rate', (
      SELECT ROUND(
        COUNT(*) FILTER (WHERE dim_is_present)::numeric
          / NULLIF(COUNT(*), 0),
        3
      )
      FROM hansard_attendance
      WHERE mp_name_cleaned = p_mp_name
    ),
    'ptba_count', (
      SELECT COUNT(*) FROM hansard_ptba WHERE mp_name_cleaned = p_mp_name
    )
  );
$$ LANGUAGE sql STABLE;

-- =============================================================
-- GRANTS — the dashboard's anon role needs read access to the tables,
-- because the RPCs above are SECURITY INVOKER (the default): they run
-- with the caller's privileges. Re-running CREATE OR REPLACE resets any
-- previously SECURITY DEFINER functions to INVOKER, so keep these grants
-- applied. All data here is public parliamentary record; writes still
-- require the service role key.
-- =============================================================
GRANT SELECT ON hansard_sittings, hansard_attendance, hansard_ptba,
  hansard_speeches, hansard_ai_summaries TO anon;

-- RLS read policies — the tables have Row Level Security enabled, and the
-- RPCs run as the caller (SECURITY INVOKER), so anon needs an explicit
-- SELECT policy on each table or every query returns zero rows. The data
-- is public parliamentary record; writes are unaffected (service role
-- bypasses RLS).
DROP POLICY IF EXISTS "public read" ON hansard_sittings;
CREATE POLICY "public read" ON hansard_sittings FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "public read" ON hansard_attendance;
CREATE POLICY "public read" ON hansard_attendance FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "public read" ON hansard_ptba;
CREATE POLICY "public read" ON hansard_ptba FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "public read" ON hansard_speeches;
CREATE POLICY "public read" ON hansard_speeches FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "public read" ON hansard_ai_summaries;
CREATE POLICY "public read" ON hansard_ai_summaries FOR SELECT TO anon USING (true);
