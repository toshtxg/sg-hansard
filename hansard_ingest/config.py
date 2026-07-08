"""Environment-driven configuration for the ingestion pipeline.

All knobs are read from environment variables (loaded from ``.env`` if
present). See ``README.md`` for the full list of supported variables and
their defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Bump when changing behaviour so logs make it clear which version ran.
SCRIPT_VERSION = "2026-07-05.6"

BASE_URL = "https://sprs.parl.gov.sg/search/getHansardReport/"


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else str(v)


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None and str(v).strip() != "" else default
    except ValueError:
        return default


DEBUG = env_bool("DEBUG", False)
SAVE_JSON = env_bool("SAVE_JSON", False) if DEBUG else False

# Optional override range (ISO: YYYY-MM-DD)
START_DATE_ISO = env_str("START_DATE", "")
END_DATE_ISO = env_str("END_DATE", "")

# Optional safety cap per run (good for GitHub Actions). Set to 0 to disable.
# For the auto/rolling window this keeps the most recent N days ending today;
# for an explicit START_DATE backfill it marches forward N days from the start.
MAX_DAYS_PER_RUN = env_int("MAX_DAYS_PER_RUN", 21)

# When auto-resuming from the latest sitting in the DB, re-ingest this many days
# back from (and including) the latest sitting. This retries days that failed
# transiently and picks up post-publication revisions to recent Hansards.
# Upserts are idempotent so re-processing is safe.
INGEST_LOOKBACK_DAYS = env_int("INGEST_LOOKBACK_DAYS", 7)

# Politeness delay (seconds) between per-day fetches.
FETCH_SLEEP_SECS = env_int("FETCH_SLEEP_SECS", 1)

# Backstop alarm: when true, a run where every scanned day failed to fetch and
# none succeeded (a total upstream blackout, distinct from a recess) exits
# non-zero so the GitHub Action turns red. Off by default so ordinary transient
# outages stay green; opt in to be paged on a sustained/permanent break.
ALERT_ON_TOTAL_BLACKOUT = env_bool("ALERT_ON_TOTAL_BLACKOUT", False)

# Supabase
SUPABASE_URL = env_str("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = env_str("SUPABASE_SERVICE_ROLE_KEY", "")

# If true, parse + write CSV/JSON locally but do NOT talk to Supabase
SKIP_DB = env_bool("SKIP_DB", False)

# Optional single-run date override (accepts YYYY-MM-DD or DD-MM-YYYY)
RUN_DATE = env_str("RUN_DATE", "")

# ---- AI summary (optional) ----
AI_ENABLED = env_bool("AI_ENABLED", False)
AI_PROVIDER = env_str("AI_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY = env_str("OPENAI_API_KEY", "")
OPENAI_MODEL = env_str("OPENAI_MODEL", "gpt-4o-mini")
AI_MAX_CHARS = env_int("AI_MAX_CHARS", 12000)
AI_DRY_RUN = env_bool("AI_DRY_RUN", False)  # if true, generate summary but don't write to DB
# Re-generate sitting summaries even when a row already exists. Off by default so
# the daily lookback window doesn't re-pay for summaries it already has.
AI_FORCE = env_bool("AI_FORCE", False)
