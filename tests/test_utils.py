"""Unit tests for hansard_ingest.utils — date parsing, whitespace, JSON scrubbing."""

import math
from datetime import date

import pandas as pd

from hansard_ingest.utils import (
    ddmmyyyy_from_date,
    extract_year,
    normalize_df_pk_cols,
    normalize_ws,
    parse_day_month,
    parse_run_date,
    parse_sitting_date,
    scrub_records_for_json,
    word_count,
)


# ---------------- normalize_ws ----------------

def test_normalize_ws_collapses_and_replaces_nbsp():
    assert normalize_ws("Chan  Chun   Sing") == "Chan Chun Sing"
    assert normalize_ws("  leading and trailing  ") == "leading and trailing"
    assert normalize_ws(None) == ""


# ---------------- word_count ----------------

def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0
    assert word_count(None) == 0


# ---------------- parse_sitting_date ----------------

def test_parse_sitting_date_ddmmyyyy():
    assert parse_sitting_date("07-01-2025") == date(2025, 1, 7)


# ---------------- parse_run_date ----------------

def test_parse_run_date_both_formats():
    assert parse_run_date("2025-01-07") == date(2025, 1, 7)
    assert parse_run_date("07-01-2025") == date(2025, 1, 7)


def test_parse_run_date_invalid_and_empty():
    assert parse_run_date("") is None
    assert parse_run_date("not-a-date") is None


# ---------------- parse_day_month ----------------

def test_parse_day_month_abbrev_and_full():
    assert parse_day_month("7 Jan", 2025) == date(2025, 1, 7)
    assert parse_day_month("7 January", 2025) == date(2025, 1, 7)


def test_parse_day_month_invalid():
    assert parse_day_month("", 2025) is None
    assert parse_day_month("garbage", 2025) is None


# ---------------- extract_year ----------------

def test_extract_year_variants():
    assert extract_year(2024, 1999) == 2024
    assert extract_year("2024", 1999) == 2024
    assert extract_year("2017/2018", 1999) == 2017
    assert extract_year("FY2017/2018", 1999) == 2017


def test_extract_year_fallback():
    assert extract_year(None, 2020) == 2020
    assert extract_year("", 2020) == 2020
    assert extract_year("no year here", 2020) == 2020


# ---------------- ddmmyyyy_from_date ----------------

def test_ddmmyyyy_from_date():
    assert ddmmyyyy_from_date(date(2025, 1, 7)) == "07-01-2025"


# ---------------- scrub_records_for_json ----------------

def test_scrub_records_replaces_nan_and_inf_with_none():
    records = [{
        "a": 1,
        "b": None,
        "c": float("nan"),
        "d": math.inf,
        "e": "keep",
    }]
    out = scrub_records_for_json(records)
    assert out == [{"a": 1, "b": None, "c": None, "d": None, "e": "keep"}]


# ---------------- normalize_df_pk_cols ----------------

def test_normalize_df_pk_cols_strips_and_collapses():
    df = pd.DataFrame({
        "sitting_date": ["2025-01-07", "2025-01-07"],
        "mp_name_raw": ["Mr  Chan Chun Sing ", "Ms Rachel Ong"],
    })
    out = normalize_df_pk_cols(df, ["mp_name_raw"])
    assert out["mp_name_raw"].tolist() == ["Mr Chan Chun Sing", "Ms Rachel Ong"]
    # original untouched (copy semantics)
    assert df["mp_name_raw"].iloc[0] == "Mr  Chan Chun Sing "


def test_normalize_df_pk_cols_empty():
    df = pd.DataFrame(columns=["mp_name_raw"])
    out = normalize_df_pk_cols(df, ["mp_name_raw"])
    assert out.empty
