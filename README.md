# sg-hansard

Ingestion pipeline for Singapore Parliament Hansard transcripts. Pulls each
sitting's JSON from the Parliament API, parses attendance / PTBA / speeches
out of the embedded HTML, optionally generates AI summaries, and upserts
everything into Supabase. A daily GitHub Actions cron keeps the database
current; the parsed data backs a separate React dashboard.

> **PTBA** = *Permission To Be Absent*, the formal mechanism by which Members
> apply for approved leave from a sitting.

---

## What you get out of it

Four Supabase tables, populated idempotently per sitting date:

| Table                  | Primary key                                        | What it holds                                             |
| ---------------------- | -------------------------------------------------- | --------------------------------------------------------- |
| `hansard_sittings`     | `sitting_date`                                     | One row per sitting, with the source URL                  |
| `hansard_attendance`   | `sitting_date, mp_name_raw`                        | Per-MP presence flag + Speaker / Deputy Speaker dimension |
| `hansard_ptba`         | `sitting_date, mp_name_raw, ptba_from, ptba_to`    | Approved leave windows that overlap the sitting           |
| `hansard_speeches`     | `sitting_date, row_num`                            | Each speech / question / written answer with metadata     |

Two optional AI tables (only populated when `AI_ENABLED=true`):

| Table                  | Primary key      | What it holds                                  |
| ---------------------- | ---------------- | ---------------------------------------------- |
| `hansard_ai_summaries` | `sitting_date`   | One 3-sentence neutral summary per sitting     |
| `hansard_speeches`*    | (existing rows)  | Per-row `one_liner`, `themes`, `key_claims`    |

\* per-speech summaries are written as additional columns on `hansard_speeches`.

The dashboard layer expects the RPCs and indexes defined in
[`db/dashboard_rpcs.sql`](db/dashboard_rpcs.sql).

---

## Architecture at a glance

```
┌────────────────────────┐    fetch.py      ┌─────────────────────┐
│ sprs.parl.gov.sg       │ ───────────────▶ │ Hansard JSON payload │
│ getHansardReport API   │                  └──────────┬──────────┘
└────────────────────────┘                             │
                                                       ▼
                          ┌──────────────────────────────────────────┐
                          │ parse.py + names.py                      │
                          │  • attendance / PTBA / speeches DataFrames│
                          │  • Chair tracking, fuzzy name matching   │
                          └──────────┬───────────────────────────────┘
                                     │
                          ┌──────────┴──────────────┐
                          ▼                         ▼
                ┌──────────────────┐   (optional)  ┌──────────────────────┐
                │ db.py upsert_all │ ◀──────────── │ ai_summary.py        │
                │ → Supabase       │               │ ai_speech_summary.py │
                └──────────────────┘               └──────────────────────┘
```

`main.py` orchestrates the loop over a date range; `ingest.py` is the thin
CLI entrypoint.

---

## Prerequisites

- Python 3.11+ (the GitHub Action uses 3.11)
- A Supabase project with the four `hansard_*` tables above
- *(optional)* OpenAI API key for AI summaries

---

## Quickstart

```bash
# 1. Clone and enter the repo
git clone https://github.com/toshtxg/sg-hansard.git
cd sg-hansard

# 2. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# edit .env: at minimum SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

# 4. Apply the dashboard SQL migration in Supabase
#    Supabase Dashboard → SQL Editor → paste db/dashboard_rpcs.sql → Run

# 5. Dry-run a single sitting without touching the DB
SKIP_DB=true DEBUG=true RUN_DATE=2025-01-07 python ingest.py
```

Once the dry run looks healthy, drop `SKIP_DB=true` to write to Supabase.

---

## Configuration

All configuration is environment-driven. See [`.env.example`](.env.example)
for a starter file. Key variables:

### Supabase (required unless `SKIP_DB=true`)

| Variable                       | Description                                  |
| ------------------------------ | -------------------------------------------- |
| `SUPABASE_URL`                 | Project URL (e.g. `https://xxx.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY`    | Service role key (writes need it)            |

### Date range / control flow

| Variable               | Default                                  | Notes                                                              |
| ---------------------- | ---------------------------------------- | ------------------------------------------------------------------ |
| `RUN_DATE`             | _unset_                                  | Single-date run. Accepts `YYYY-MM-DD` or `DD-MM-YYYY`              |
| `START_DATE`           | lookback window from the latest sitting  | ISO date. Falls back to `2020-01-01` if the table is empty         |
| `END_DATE`             | today                                    | ISO date                                                           |
| `INGEST_LOOKBACK_DAYS` | `7`                                      | When `START_DATE` is unset, re-ingest this many days back from (and including) the latest sitting in Supabase. Retries transiently-failed days and picks up post-publication Hansard revisions; upserts are idempotent so this is safe |
| `FETCH_SLEEP_SECS`     | `1`                                      | Politeness delay (seconds) between per-day fetches                 |
| `MAX_DAYS_PER_RUN`     | `0` (disabled)                           | Safety cap per run (handy on Actions). Set to e.g. `30`            |
| `SKIP_DB`              | `false`                                  | Parse only, never call Supabase                                    |
| `DEBUG`                | `false`                                  | Verbose logs + write per-sitting CSVs                              |
| `SAVE_JSON`            | `false`                                  | When `DEBUG=true`, also dump raw API JSON to disk                  |

The fetch layer also retries transient HTTP errors (429/5xx) with exponential
backoff, and the run ends with a one-line summary. If any day fails to fetch,
parse, or upsert, the process exits non-zero so the GitHub Action turns red
and notifies the owner. Non-sitting days (empty payloads) are not failures.

### AI summaries (optional)

| Variable          | Default         | Notes                                                  |
| ----------------- | --------------- | ------------------------------------------------------ |
| `AI_ENABLED`      | `false`         | Master switch                                          |
| `AI_PROVIDER`     | `openai`        | Only `openai` is implemented today                     |
| `OPENAI_API_KEY`  | _unset_         | Required when `AI_ENABLED=true`                        |
| `OPENAI_MODEL`    | `gpt-4o-mini`   | Used for both sitting and per-speech summaries         |
| `AI_MAX_CHARS`    | `12000`         | Hard cap on the sitting-summary prompt size            |
| `AI_DRY_RUN`      | `false`         | Generate but do not persist summaries                  |
| `AI_FORCE`        | `false`         | Re-generate sitting summaries even when one already exists. By default dates with an existing `hansard_ai_summaries` row are skipped, so the daily lookback window doesn't re-pay for summaries |

---

## Usage

### Run the pipeline locally

```bash
# Catch up from the last sitting in DB to today
python ingest.py

# Re-ingest one specific sitting
RUN_DATE=2025-01-07 python ingest.py

# Backfill a window
START_DATE=2024-01-01 END_DATE=2024-03-31 python ingest.py
```

### Backfill scripts

```bash
# Re-ingest every sitting already in hansard_sittings (e.g. after a parser fix)
python scripts/backfill_existing_sittings.py

# Backfill per-speech AI summaries over a date window
python scripts/backfill_summaries.py \
    --start_date 2024-01-01 --end_date 2024-12-31 \
    --workers 8
```

### Scheduled runs (GitHub Actions)

[`.github/workflows/hansard_ingest.yml`](.github/workflows/hansard_ingest.yml)
runs daily at 16:00 UTC (00:00 SGT) — Hansard data is published next-day, and
the `INGEST_LOOKBACK_DAYS` window keeps daily runs cheap while retrying any
recently-failed days. A failed day makes the run exit non-zero, so the Action
turns red and GitHub notifies the owner. Set the following repository
secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`.

### Tests

```bash
pip install -r requirements-dev.txt   # installs requirements.txt + pytest
pytest
```

Unit tests live in [`tests/`](tests/) and cover name cleaning, parsing,
per-speech summary plumbing, and the date/JSON helpers. `pytest.ini` puts the
repo root on `sys.path` so `import hansard_ingest` works without installation.

---

## Repository layout

```
sg-hansard/
├── ingest.py                      # CLI entrypoint → hansard_ingest.main.ingest()
├── requirements.txt
├── requirements-dev.txt           # test deps (pytest)
├── pytest.ini
├── .env.example
├── .github/workflows/
│   └── hansard_ingest.yml         # Daily cron
├── db/
│   └── dashboard_rpcs.sql         # Supabase RPCs + indexes for the dashboard
├── hansard_ingest/                # Ingestion package
│   ├── config.py                  # Env-driven configuration
│   ├── fetch.py                   # HTTP fetch from the Parliament API
│   ├── parse.py                   # JSON → attendance / PTBA / speech DataFrames
│   ├── names.py                   # Name cleaning + Chair role + fuzzy matching
│   ├── db.py                      # Supabase client + idempotent upserts
│   ├── ai_summary.py              # Sitting-level 3-sentence summary (optional)
│   ├── ai_speech_summary.py       # Per-speech structured summary (optional)
│   ├── utils.py                   # Date / JSON / CSV helpers
│   └── main.py                    # Orchestration loop
├── tests/                         # pytest unit tests
└── scripts/
    ├── backfill_existing_sittings.py
    └── backfill_summaries.py
```

---

## Troubleshooting

- **`Missing required env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY`** —
  populate `.env` or export them in your shell. Use `SKIP_DB=true` for
  parser-only runs.
- **`ON CONFLICT DO UPDATE command cannot affect row a second time`** —
  the parsed payload contains duplicate PKs. `db.upsert_all` already
  normalises and de-duplicates; if you still hit this, run with
  `DEBUG=true` and inspect the `[DEBUG] Duplicate ... PK rows` log.
- **`Upsert failed for hansard_speeches ... unknown column ...`** —
  your DB schema is older than the parser. Either run the migration in
  `db/dashboard_rpcs.sql` and add any missing columns, or rely on the
  built-in fallback that retries without the new columns.
- **`DAILY_LIMIT_REACHED`** in the speech-summary backfill — OpenAI's
  daily quota was hit. The script exits 0 cleanly; rerun the same
  command tomorrow and it will skip already-summarised rows.

---

## License

No license file at the moment. Treat as "all rights reserved" until one
is added.
