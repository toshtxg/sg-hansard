"""Supabase client + idempotent upserts for the parsed tables.

Each table has an explicit primary key and ``on_conflict`` target so
re-running the pipeline for the same date is a no-op. We normalise PK
columns and drop in-payload duplicates before upserting to avoid the
``ON CONFLICT DO UPDATE command cannot affect row a second time``
Postgres error that fires when one statement carries duplicate keys.
"""

from datetime import date, datetime
from typing import Optional

import pandas as pd

from .config import (
    AI_DRY_RUN,
    AI_ENABLED,
    DEBUG,
    SKIP_DB,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from .ai_speech_summary import (
    build_summary_update,
    infer_role_from_label,
    needs_summary,
    summarize_row,
)
from .utils import chunk_records, normalize_df_pk_cols, scrub_records_for_json

# Supabase is optional for local parsing runs (e.g., SKIP_DB=true).
# We import it lazily so the script can run even if the package isn't installed.
try:
    from supabase import create_client, Client  # type: ignore
except ModuleNotFoundError:
    create_client = None  # type: ignore
    Client = object  # type: ignore


def require_env():
    if SKIP_DB:
        return
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_ROLE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing))


def supabase_client() -> Client:
    require_env()
    if create_client is None:
        raise RuntimeError(
            "Python package 'supabase' is not installed. Install it with: pip install supabase"
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_latest_sitting(sb: Client) -> Optional[date]:
    resp = sb.table("hansard_sittings").select("sitting_date").order("sitting_date", desc=True).limit(1).execute()
    if resp.data:
        return datetime.fromisoformat(resp.data[0]["sitting_date"]).date()
    return None


def ai_summary_exists(sb: Client, sitting_iso: str) -> bool:
    """Return True if hansard_ai_summaries already has a row for this date.

    Best-effort: if the table is missing or the query fails, return False so the
    caller falls back to generating (the upsert path is itself fault-tolerant).
    """
    try:
        resp = (
            sb.table("hansard_ai_summaries")
            .select("sitting_date")
            .eq("sitting_date", sitting_iso)
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


def summarize_speeches_for_date(sb: Client, sitting_iso: str) -> None:
    if not AI_ENABLED or AI_DRY_RUN:
        return

    try:
        resp = (
            sb.table("hansard_speeches")
            .select(
                "sitting_date,row_num,speech_details,mp_name_fuzzy_matched,mp_name_raw,dim_speaker,summary_version,one_liner"
            )
            .eq("sitting_date", sitting_iso)
            .order("row_num")
            .execute()
        )
    except Exception as e:
        print(f"Speech summary select failed for {sitting_iso}: {e}")
        return

    rows = resp.data or []
    for row in rows:
        if not needs_summary(row.get("one_liner"), row.get("summary_version")):
            continue
        if not row.get("sitting_date") or row.get("row_num") is None:
            continue
        speech = str(row.get("speech_details") or "")
        speaker_label = row.get("mp_name_raw") or ""
        metadata = {
            "speaker_name": speaker_label,
            "role": infer_role_from_label(speaker_label),
            "sitting_date": row.get("sitting_date") or sitting_iso,
        }

        try:
            summary = summarize_row(speech, metadata)
        except Exception as e:
            print(f"Speech summary failed for {sitting_iso} row {row.get('row_num')}: {e}")
            continue

        if not summary:
            continue

        update = build_summary_update(summary)
        try:
            (
                sb.table("hansard_speeches")
                .update(update)
                .eq("sitting_date", row["sitting_date"])
                .eq("row_num", row["row_num"])
                .execute()
            )
        except Exception as e:
            print(f"Speech summary update failed for {sitting_iso} row {row.get('row_num')}: {e}")


def upsert_all(
    sb: Client,
    df_att: pd.DataFrame,
    df_ptba: pd.DataFrame,
    df_speech: pd.DataFrame,
    sitting_iso: str,
    source_url: str,
    ai_summary_row: Optional[dict] = None,
):
    """Upsert parsed data into Supabase.

    Postgres raises `ON CONFLICT DO UPDATE command cannot affect row a second time`
    when a *single upsert statement* contains multiple rows with the same conflict key.
    This usually means our parsed payload contains duplicates for the table's PK.

    We therefore:
      1) normalize PK fields (strip whitespace; stable string conversion)
      2) drop duplicates on the real PK
      3) upsert in batches with explicit on_conflict targets
    """

    # Attendance PK: (sitting_date, mp_name_raw)
    df_att_u = df_att
    if df_att_u is not None and not df_att_u.empty and {"sitting_date", "mp_name_raw"}.issubset(df_att_u.columns):
        df_att_u = normalize_df_pk_cols(df_att_u, ["sitting_date", "mp_name_raw"])
        if DEBUG:
            dup_mask = df_att_u.duplicated(subset=["sitting_date", "mp_name_raw"], keep=False)
            if dup_mask.any():
                print("[DEBUG] Duplicate attendance PK rows BEFORE de-dup:")
                print(df_att_u.loc[dup_mask, ["sitting_date", "mp_name_raw"]].value_counts().head(50))
        df_att_u = df_att_u.drop_duplicates(subset=["sitting_date", "mp_name_raw"], keep="first")

    # PTBA PK: (sitting_date, mp_name_raw, ptba_from, ptba_to)
    df_ptba_u = df_ptba
    if df_ptba_u is not None and not df_ptba_u.empty and {"sitting_date", "mp_name_raw", "ptba_from", "ptba_to"}.issubset(df_ptba_u.columns):
        df_ptba_u = normalize_df_pk_cols(df_ptba_u, ["sitting_date", "mp_name_raw", "ptba_from", "ptba_to"])
        if DEBUG:
            dup_mask = df_ptba_u.duplicated(subset=["sitting_date", "mp_name_raw", "ptba_from", "ptba_to"], keep=False)
            if dup_mask.any():
                print("[DEBUG] Duplicate PTBA PK rows BEFORE de-dup:")
                print(df_ptba_u.loc[dup_mask, ["sitting_date", "mp_name_raw", "ptba_from", "ptba_to"]].value_counts().head(50))
        df_ptba_u = df_ptba_u.drop_duplicates(subset=["sitting_date", "mp_name_raw", "ptba_from", "ptba_to"], keep="first")

    # Speeches PK: (sitting_date, row_num)
    df_speech_u = df_speech
    if df_speech_u is not None and not df_speech_u.empty and {"sitting_date", "row_num"}.issubset(df_speech_u.columns):
        df_speech_u = normalize_df_pk_cols(df_speech_u, ["sitting_date"])
        if DEBUG:
            dup_mask = df_speech_u.duplicated(subset=["sitting_date", "row_num"], keep=False)
            if dup_mask.any():
                print("[DEBUG] Duplicate speeches PK rows BEFORE de-dup:")
                print(df_speech_u.loc[dup_mask, ["sitting_date", "row_num"]].value_counts().head(50))
        df_speech_u = df_speech_u.drop_duplicates(subset=["sitting_date", "row_num"], keep="first")

    def _json_records(df: pd.DataFrame):
        if df is None or df.empty:
            return []
        return scrub_records_for_json(df.to_dict("records"))

    # Upsert batches with explicit conflict targets
    try:
        for batch in chunk_records(_json_records(df_att_u), 500):
            sb.table("hansard_attendance").upsert(batch, on_conflict="sitting_date,mp_name_raw").execute()
    except Exception as e:
        raise RuntimeError(f"Upsert failed for hansard_attendance ({sitting_iso}): {e}")

    try:
        for batch in chunk_records(_json_records(df_ptba_u), 500):
            sb.table("hansard_ptba").upsert(batch, on_conflict="sitting_date,mp_name_raw,ptba_from,ptba_to").execute()
    except Exception as e:
        raise RuntimeError(f"Upsert failed for hansard_ptba ({sitting_iso}): {e}")

    def _upsert_speeches(df: pd.DataFrame):
        for batch in chunk_records(_json_records(df), 300):
            sb.table("hansard_speeches").upsert(batch, on_conflict="sitting_date,row_num").execute()

    try:
        _upsert_speeches(df_speech_u)
    except Exception as e:
        # Backward-compat: if the DB schema hasn't been updated with new speech columns yet,
        # retry by dropping known "extra" columns.
        extra_cols = [
            "discussion_title",
            "section_type",
            "dim_is_question_for_oral_answer",
            "dim_is_oral_speech",
            "dim_is_written_answer_not_answered",
            "dim_is_written_answer_to_questions",
        ]
        msg = str(e)
        present = [c for c in extra_cols if df_speech_u is not None and c in df_speech_u.columns]
        if present and any(c in msg for c in present):
            if DEBUG:
                print(f"[DEBUG] hansard_speeches upsert failed; retrying without columns: {present}")
            df_retry = df_speech_u.drop(columns=present)
            try:
                _upsert_speeches(df_retry)
            except Exception as e2:
                raise RuntimeError(f"Upsert failed for hansard_speeches ({sitting_iso}): {e2}")
        else:
            raise RuntimeError(f"Upsert failed for hansard_speeches ({sitting_iso}): {e}")

    # Delete stale speech rows for this sitting: if a re-ingest of the same date
    # produced fewer rows than a previous run (e.g. a Hansard revision), rows
    # beyond the current max row_num would otherwise linger. Best-effort only —
    # never fail the ingest over cleanup.
    if df_speech_u is not None and not df_speech_u.empty and "row_num" in df_speech_u.columns:
        try:
            max_row_num = int(df_speech_u["row_num"].max())
            (
                sb.table("hansard_speeches")
                .delete()
                .eq("sitting_date", sitting_iso)
                .gt("row_num", max_row_num)
                .execute()
            )
        except Exception as e:
            print(f"Stale speech cleanup skipped for {sitting_iso}: {e}")

    try:
        sb.table("hansard_sittings").upsert(
            {"sitting_date": sitting_iso, "source_url": source_url},
            on_conflict="sitting_date",
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Upsert failed for hansard_sittings ({sitting_iso}): {e}")

    # Optional AI summary table (safe if AI not enabled, and safe if table doesn't exist)
    if AI_ENABLED and ai_summary_row and ai_summary_row.get("sitting_date") == sitting_iso:
        try:
            # NOTE: assumes a table named hansard_ai_summaries exists with PK on sitting_date
            # Columns expected: sitting_date, provider, model, summary_3_sentences, updated_at
            # If your schema differs, adjust here.
            cleaned = scrub_records_for_json([ai_summary_row])[0]
            sb.table("hansard_ai_summaries").upsert(cleaned, on_conflict="sitting_date").execute()
        except Exception as e:
            # Don't fail ingestion if AI summary insert fails
            if DEBUG:
                print(f"[DEBUG] AI summary upsert skipped/failed for {sitting_iso}: {e}")

    # Optional per-speech summaries (safe to skip if AI not enabled or schema missing)
    try:
        summarize_speeches_for_date(sb, sitting_iso)
    except Exception as e:
        print(f"Speech summary pass failed for {sitting_iso}: {e}")
