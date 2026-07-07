"""Pipeline orchestration: walk a date range and ingest each sitting.

Resolves the date window from environment config (or Supabase state),
then for each day: fetch -> parse -> (optional AI summary) -> upsert.
Failures on a single day are logged and skipped so one bad day cannot
abort a long backfill window.
"""

import sys
import time
from datetime import date, datetime, timedelta

from .ai_summary import generate_ai_summary
from .config import (
    AI_DRY_RUN,
    AI_ENABLED,
    AI_FORCE,
    DEBUG,
    FETCH_SLEEP_SECS,
    SAVE_JSON,
    END_DATE_ISO,
    INGEST_LOOKBACK_DAYS,
    MAX_DAYS_PER_RUN,
    RUN_DATE,
    SCRIPT_VERSION,
    SKIP_DB,
    START_DATE_ISO,
)
from .db import ai_summary_exists, get_latest_sitting, supabase_client, upsert_all
from .fetch import fetch_hansard_json
from .parse import parse_one_sitting
from .utils import ddmmyyyy_from_date, maybe_write_csv, maybe_write_json, parse_run_date


def ingest():
    sb = None if SKIP_DB else supabase_client()

    today = date.today()

    lookback_note = ""
    run_dt = parse_run_date(RUN_DATE)
    if run_dt is not None:
        # Single-date test run
        start_dt = run_dt
        end_dt = run_dt
    else:
        end_dt = datetime.strptime(END_DATE_ISO, "%Y-%m-%d").date() if END_DATE_ISO else today

        if START_DATE_ISO:
            start_dt = datetime.strptime(START_DATE_ISO, "%Y-%m-%d").date()
        else:
            latest = get_latest_sitting(sb) if sb is not None else None
            if latest:
                # Re-ingest a rolling window ending at (and including) the latest
                # sitting so transiently-failed days are retried and post-publication
                # Hansard revisions are picked up. Upserts are idempotent.
                start_dt = latest - timedelta(days=max(INGEST_LOOKBACK_DAYS - 1, 0))
                lookback_note = f", lookback={INGEST_LOOKBACK_DAYS}d from latest sitting {latest.isoformat()}"
            else:
                start_dt = date(2020, 1, 1)

        # Optional cap per run (GitHub Actions friendly). Set MAX_DAYS_PER_RUN=0 to disable.
        if MAX_DAYS_PER_RUN and MAX_DAYS_PER_RUN > 0:
            if (end_dt - start_dt).days + 1 > MAX_DAYS_PER_RUN:
                end_dt = start_dt + timedelta(days=MAX_DAYS_PER_RUN - 1)

    print(
        "Ingest range: "
        f"{start_dt.isoformat()} -> {end_dt.isoformat()} "
        f"(ver={SCRIPT_VERSION}, RUN_DATE={RUN_DATE or 'auto'}, "
        f"DEBUG={DEBUG}, SAVE_JSON={SAVE_JSON}, SKIP_DB={SKIP_DB}{lookback_note})"
    )

    days_scanned = 0
    sittings_ingested = 0
    failures: list[str] = []

    d = start_dt
    while d <= end_dt:
        ddmmyyyy = ddmmyyyy_from_date(d)
        days_scanned += 1

        try:
            data = fetch_hansard_json(ddmmyyyy)
        except Exception as e:
            print(f"Fetch failed for {ddmmyyyy}: {e}")
            failures.append(ddmmyyyy)
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue

        if DEBUG and SAVE_JSON:
            maybe_write_json(data, f"hansard_{ddmmyyyy}.json")

        try:
            df_att, df_ptba, df_speech, source_url, parliament_no, sitting_dt = parse_one_sitting(data)
        except Exception as e:
            print(f"Parse failed for {ddmmyyyy}: {e}")
            failures.append(ddmmyyyy)
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue

        if DEBUG:
            maybe_write_csv(df_att, f"attendance_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_ptba, f"ptba_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_speech, f"speech_list_{ddmmyyyy}.csv")

        if len(df_att) == 0 and len(df_speech) == 0:
            # Non-sitting day (empty payload) — expected, not a failure.
            print(f"No sitting detected for {ddmmyyyy}; skipping insert")
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue

        # ---- AI summary (optional) ----
        # Skip regeneration when a summary already exists (the daily lookback
        # window re-processes recent days). Override with AI_FORCE=true.
        ai_row = None
        if AI_ENABLED:
            skip_ai = False
            if not AI_FORCE and sb is not None and ai_summary_exists(sb, d.isoformat()):
                skip_ai = True
                if DEBUG:
                    print(f"[DEBUG] AI summary already present for {ddmmyyyy}; skipping generation")
            if not skip_ai:
                try:
                    ai_row = generate_ai_summary(d.isoformat(), df_speech)
                    if DEBUG and ai_row:
                        preview = ai_row.get("summary_3_sentences", "")[:120]
                        print(f"[DEBUG] AI summary generated for {ddmmyyyy}: {preview}...")
                    if AI_DRY_RUN and ai_row:
                        print(f"[AI_DRY_RUN] {d.isoformat()} summary:\n{ai_row.get('summary_3_sentences','')}")
                except Exception as e:
                    print(f"AI summary failed for {ddmmyyyy}: {e}")

        if sb is None:
            print(f"SKIP_DB=true; parsed {ddmmyyyy}: att={len(df_att)} ptba={len(df_ptba)} speech={len(df_speech)}")
            sittings_ingested += 1
        else:
            try:
                if AI_DRY_RUN:
                    # Prevent AI summary DB writes during dry run
                    ai_row = None
                upsert_all(sb, df_att, df_ptba, df_speech, d.isoformat(), source_url, ai_summary_row=ai_row)
                print(f"Inserted {ddmmyyyy}: att={len(df_att)} ptba={len(df_ptba)} speech={len(df_speech)}")
                sittings_ingested += 1
            except Exception as e:
                print(f"DB insert failed for {ddmmyyyy}: {e}")
                failures.append(ddmmyyyy)

        d += timedelta(days=1)
        time.sleep(FETCH_SLEEP_SECS)

    # ---- Run summary ----
    summary = (
        f"Run summary: days_scanned={days_scanned}, sittings_ingested={sittings_ingested}, "
        f"failures={len(failures)}"
    )
    if failures:
        summary += f" ({', '.join(failures)})"
    print(summary)

    if failures:
        # Exit non-zero so the GitHub Action turns red and notifies the owner.
        sys.exit(1)
