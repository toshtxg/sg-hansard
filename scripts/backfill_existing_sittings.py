"""Re-ingest every sitting date already in ``hansard_sittings``.

Use after schema or parser changes to refresh attendance / PTBA / speech
rows (and optionally sitting-level AI summaries) without redefining the
date window. Reads dates from Supabase rather than the API, so it only
touches sittings the system already knows about.
"""

from datetime import datetime

from hansard_ingest.ai_summary import generate_ai_summary
from hansard_ingest.config import AI_DRY_RUN, AI_ENABLED, DEBUG, SAVE_JSON, SKIP_DB, SCRIPT_VERSION
from hansard_ingest.db import refresh_dashboard_cache, supabase_client, upsert_all
from hansard_ingest.fetch import fetch_hansard_json
from hansard_ingest.parse import parse_one_sitting
from hansard_ingest.utils import ddmmyyyy_from_date, maybe_write_csv, maybe_write_json


def main() -> None:
    if SKIP_DB:
        raise RuntimeError("SKIP_DB=true; set SKIP_DB=false for backfill.")

    sb = supabase_client()
    resp = sb.table("hansard_sittings").select("sitting_date").order("sitting_date").execute()
    rows = resp.data or []
    dates = sorted({r.get("sitting_date") for r in rows if r.get("sitting_date")})

    print(f"Backfill sittings: {len(dates)} dates (ver={SCRIPT_VERSION})")

    for sitting_iso in dates:
        try:
            d = datetime.fromisoformat(sitting_iso).date()
        except ValueError:
            print(f"Skip invalid sitting_date: {sitting_iso}")
            continue

        ddmmyyyy = ddmmyyyy_from_date(d)

        try:
            data = fetch_hansard_json(ddmmyyyy)
        except Exception as e:
            print(f"Fetch failed for {ddmmyyyy}: {e}")
            continue

        if DEBUG and SAVE_JSON:
            maybe_write_json(data, f"hansard_{ddmmyyyy}.json")

        try:
            df_att, df_ptba, df_speech, source_url, parliament_no, sitting_dt = parse_one_sitting(data)
        except Exception as e:
            print(f"Parse failed for {ddmmyyyy}: {e}")
            continue

        ai_row = None
        if AI_ENABLED:
            try:
                ai_row = generate_ai_summary(d.isoformat(), df_speech)
                if AI_DRY_RUN:
                    ai_row = None
            except Exception as e:
                print(f"AI summary failed for {ddmmyyyy}: {e}")

        if DEBUG:
            maybe_write_csv(df_att, f"attendance_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_ptba, f"ptba_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_speech, f"speech_list_{ddmmyyyy}.csv")

        if len(df_att) == 0 and len(df_speech) == 0:
            print(f"No sitting detected for {ddmmyyyy}; skipping insert")
            continue

        try:
            upsert_all(sb, df_att, df_ptba, df_speech, d.isoformat(), source_url, ai_summary_row=ai_row)
            print(f"Inserted {ddmmyyyy}: att={len(df_att)} ptba={len(df_ptba)} speech={len(df_speech)}")
        except Exception as e:
            print(f"DB insert failed for {ddmmyyyy}: {e}")

    refresh_dashboard_cache(sb)


if __name__ == "__main__":
    main()
