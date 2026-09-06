"""Pipeline orchestration: walk a date range and ingest each sitting.

Resolves the date window from environment config (or Supabase state),
then for each day: fetch -> parse -> (optional AI summary) -> upsert.
Failures on a single day are logged and skipped so one bad day cannot
abort a long backfill window.
"""

import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

from .ai_summary import generate_ai_summary
from .config import (
    AI_DRY_RUN,
    AI_ENABLED,
    AI_FORCE,
    ALERT_ON_TOTAL_BLACKOUT,
    DEBUG,
    FETCH_SLEEP_SECS,
    GIT_SHA,
    LOG_RUNS,
    SAVE_JSON,
    END_DATE_ISO,
    INGEST_LOOKBACK_DAYS,
    MAX_DAYS_PER_RUN,
    RUN_DATE,
    SCRIPT_VERSION,
    SKIP_DB,
    START_DATE_ISO,
)
from .db import (
    ai_summary_exists,
    get_latest_sitting,
    insert_run_log,
    supabase_client,
    upsert_all,
)
from .fetch import NoSittingReport, fetch_hansard_json, upstream_has_report
from .parse import parse_one_sitting
from .utils import ddmmyyyy_from_date, maybe_write_csv, maybe_write_json, parse_run_date


def ingest():
    started_at = datetime.now(timezone.utc)
    sb = None if SKIP_DB else supabase_client()

    today = date.today()

    # Remembered for the blackout probe after the scan loop.
    latest_known_sitting = None

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
            explicit_start = True
        else:
            explicit_start = False
            latest = get_latest_sitting(sb) if sb is not None else None
            latest_known_sitting = latest
            if latest:
                # Re-ingest a rolling window ending at (and including) the latest
                # sitting so transiently-failed days are retried and post-publication
                # Hansard revisions are picked up. Upserts are idempotent.
                start_dt = latest - timedelta(days=max(INGEST_LOOKBACK_DAYS - 1, 0))
                lookback_note = f", lookback={INGEST_LOOKBACK_DAYS}d from latest sitting {latest.isoformat()}"
            else:
                start_dt = date(2020, 1, 1)

        # Optional cap per run (GitHub Actions friendly). Set MAX_DAYS_PER_RUN=0 to disable.
        # Explicit backfills march forward from the start date; the auto/rolling
        # window keeps the most recent MAX_DAYS_PER_RUN days ending at end_dt, so a
        # long recess (a stale latest sitting) can't balloon the window into
        # hundreds of mostly-non-sitting days that each pay upstream retry backoff.
        if MAX_DAYS_PER_RUN and MAX_DAYS_PER_RUN > 0:
            if (end_dt - start_dt).days + 1 > MAX_DAYS_PER_RUN:
                if explicit_start:
                    end_dt = start_dt + timedelta(days=MAX_DAYS_PER_RUN - 1)
                else:
                    start_dt = end_dt - timedelta(days=MAX_DAYS_PER_RUN - 1)

    print(
        "Ingest range: "
        f"{start_dt.isoformat()} -> {end_dt.isoformat()} "
        f"(ver={SCRIPT_VERSION}, RUN_DATE={RUN_DATE or 'auto'}, "
        f"DEBUG={DEBUG}, SAVE_JSON={SAVE_JSON}, SKIP_DB={SKIP_DB}{lookback_note})"
    )

    days_scanned = 0
    sittings_ingested = 0
    successful_fetches = 0          # days upstream answered definitively (report or "none")
    no_sitting_days = 0             # days upstream confirmed hold no Hansard — recess, not failure
    fetch_failures: list[str] = []  # transient upstream (5xx/timeout) — self-heals, don't page
    hard_failures: list[str] = []   # parse/DB/unexpected — real problems that should page

    d = start_dt
    while d <= end_dt:
        ddmmyyyy = ddmmyyyy_from_date(d)
        days_scanned += 1

        try:
            data = fetch_hansard_json(ddmmyyyy)
        except NoSittingReport:
            # Upstream answered definitively: no Hansard for this date. That is
            # the normal state of most days, so it counts as a reachable day and
            # never touches the parser (which requires a metadata block).
            if DEBUG:
                print(f"No report upstream for {ddmmyyyy}")
            successful_fetches += 1
            no_sitting_days += 1
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue
        except requests.exceptions.RequestException as e:
            # Transient upstream error (5xx after retries, timeout, connection
            # reset). The rolling lookback window retries these on the next run,
            # so treat as a warning rather than failing the whole job.
            print(f"Fetch failed (upstream) for {ddmmyyyy}: {e}")
            fetch_failures.append(ddmmyyyy)
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue
        except Exception as e:
            print(f"Fetch failed (unexpected) for {ddmmyyyy}: {e}")
            hard_failures.append(ddmmyyyy)
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue

        # Upstream is reachable for this day (an empty payload still counts —
        # non-sitting days return an empty 200). Used to detect a total blackout.
        successful_fetches += 1

        if DEBUG and SAVE_JSON:
            maybe_write_json(data, f"hansard_{ddmmyyyy}.json")

        try:
            df_att, df_ptba, df_speech, source_url, parliament_no, sitting_dt = parse_one_sitting(data)
        except Exception as e:
            print(f"Parse failed for {ddmmyyyy}: {e}")
            hard_failures.append(ddmmyyyy)
            d += timedelta(days=1)
            time.sleep(FETCH_SLEEP_SECS)
            continue

        if DEBUG:
            maybe_write_csv(df_att, f"attendance_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_ptba, f"ptba_list_{ddmmyyyy}.csv")
            maybe_write_csv(df_speech, f"speech_list_{ddmmyyyy}.csv")

        if len(df_att) == 0 and len(df_speech) == 0:
            # Non-sitting day (payload present but empty) — expected, not a
            # failure. Distinct from NoSittingReport above, which is upstream
            # refusing the date outright; both mean "no sitting".
            print(f"No sitting detected for {ddmmyyyy}; skipping insert")
            no_sitting_days += 1
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
                hard_failures.append(ddmmyyyy)

        d += timedelta(days=1)
        time.sleep(FETCH_SLEEP_SECS)

    # ---- Run summary ----
    summary = (
        f"Run summary: days_scanned={days_scanned}, sittings_ingested={sittings_ingested}, "
        f"no_sitting_days={no_sitting_days}, upstream_failures={len(fetch_failures)}, "
        f"hard_failures={len(hard_failures)}"
    )
    if hard_failures:
        summary += f" (hard: {', '.join(hard_failures)})"
    print(summary)

    if fetch_failures:
        # Upstream (sprs.parl.gov.sg) returned 5xx/timeouts for these days. This is
        # common during recess or upstream maintenance and self-heals via the
        # rolling lookback window, so warn but do not fail the job.
        print(
            f"WARNING: {len(fetch_failures)} day(s) failed to fetch from upstream "
            f"and will be retried next run: {', '.join(fetch_failures)}"
        )

    # Optional backstop against a *permanent* upstream break (e.g. the endpoint
    # moves) silently going green forever. Two shapes count as a blackout:
    #
    #   1. Every scanned day errored outright — nothing answered at all.
    #   2. Every scanned day came back "no report" AND a date we have already
    #      ingested now also comes back "no report". Upstream's empty response
    #      is generic, so only re-asking a date with a known answer separates a
    #      genuine recess from an endpoint that has started denying everything.
    #
    # Off by default (a normal transient outage would otherwise trip it); opt in
    # via ALERT_ON_TOTAL_BLACKOUT once you want to be paged on a sustained break.
    control_probe_ok = None
    if days_scanned > 0 and sittings_ingested == 0 and no_sitting_days > 0:
        control = latest_known_sitting
        if control is None and sb is not None:
            try:
                control = get_latest_sitting(sb)
            except Exception as e:
                print(f"Blackout probe skipped (could not read latest sitting): {e}")
        if control is not None:
            control_probe_ok = upstream_has_report(ddmmyyyy_from_date(control))
            if control_probe_ok:
                print(
                    f"Blackout probe: upstream still serves {control.isoformat()}, "
                    "so the empty window is a recess, not an outage."
                )
            else:
                print(
                    f"Blackout probe: upstream reports no Hansard for {control.isoformat()}, "
                    "a sitting already in the database — upstream is not answering correctly."
                )

    total_blackout = (
        days_scanned > 0 and successful_fetches == 0 and len(fetch_failures) > 0
    ) or control_probe_ok is False

    if LOG_RUNS and sb is not None:
        insert_run_log(
            sb,
            {
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "script_version": SCRIPT_VERSION,
                "git_sha": GIT_SHA or None,
                "range_start": start_dt.isoformat(),
                "range_end": end_dt.isoformat(),
                "days_scanned": days_scanned,
                "sittings_ingested": sittings_ingested,
                "no_sitting_days": no_sitting_days,
                "transient_failures": len(fetch_failures),
                "hard_failures": len(hard_failures),
                "hard_failure_dates": hard_failures or None,
                "total_blackout": total_blackout,
                "latest_sitting": (
                    latest_known_sitting.isoformat() if latest_known_sitting else None
                ),
            },
        )

    if ALERT_ON_TOTAL_BLACKOUT and total_blackout and not hard_failures:
        print(
            "ALERT: total upstream blackout — "
            f"{days_scanned} scanned day(s) yielded no Hansard and the control "
            "probe confirmed upstream is not serving a sitting it holds. "
            "Upstream may be down or the endpoint may have changed."
        )
        sys.exit(1)

    if hard_failures:
        # Parse/DB/unexpected errors are real problems: exit non-zero so the
        # GitHub Action turns red and notifies the owner.
        sys.exit(1)
