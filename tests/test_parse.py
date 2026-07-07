"""Integration-style tests for hansard_ingest.parse — the parsing surface that
guards the production DB.

The `SAMPLE_SITTING` fixture is a hand-built (never captured from the network)
Hansard JSON payload that exercises, in a single pass:

  * DD-MM-YYYY sitting date + misspelled 'parlimentNO' metadata key
  * Speaker / Deputy Speaker / plain-MP attendance lines (incl. nested-name
    presiding-officer lines and a blank separator row)
  * a PTBA record that overlaps the sitting and ones that do not (+ mpName
    carry-forward)
  * a split-<strong> speaker label with a colon
  * a continuation paragraph merged into the previous speech
  * a '[... in the Chair.]' marker that flips the tracked chair
  * a Question-Time listing (non-oral) vs. oral speeches
  * a Written Answer section (dim_speaker/chair suppressed)
"""

import pandas as pd
import pytest

from hansard_ingest.parse import (
    infer_parliament_no_from_metadata,
    parse_one_sitting,
    ptba_overlaps_sitting,
)
from datetime import date


SAMPLE_SITTING = {
    "metadata": {
        "sittingDate": "07-01-2025",
        "parlimentNO": "14",
        "speaker": "Mr Speaker",
    },
    "attendanceList": [
        {"mpName": "Mr SPEAKER (Mr Seah Kian Peng (Marine Parade)).", "attendance": True},
        {"mpName": "Mr Deputy Speaker (Mr Christopher de Souza (Holland-Bukit Timah)).", "attendance": True},
        {"mpName": "Mr Chan Chun Sing (Tanjong Pagar), Coordinating Minister for Public Service.", "attendance": True},
        {"mpName": "Miss Rachel Ong (West Coast).", "attendance": True},
        {"mpName": "Mr Louis Ng Kok Kwang (Nee Soon).", "attendance": True},
        {"mpName": "Ms Sylvia Lim (Aljunied).", "attendance": False},
        {"mpName": "", "attendance": True},  # blank separator -> skipped
    ],
    "ptbaList": [
        {"mpName": "Ms Sylvia Lim", "from": "7 Jan", "to": "9 Jan"},      # overlaps 7 Jan
        {"mpName": "Mr Faisal Manap", "from": "1 Feb", "to": "3 Feb"},    # no overlap
        {"mpName": "", "from": "10 Feb", "to": "12 Feb"},                 # carries 'Faisal', still no overlap
    ],
    "takesSectionVOList": [
        {
            "sectionType": "BILL",
            "title": "Motion on Public Trust",
            "content": (
                "<p><strong>Mr </strong><strong>Chan Chun Sing</strong>: "
                "I beg to move that this House affirms its commitment to public trust.</p>"
                "<p>This measure will strengthen accountability across all agencies.</p>"
                "<p>[Mr Deputy Speaker (Mr Christopher de Souza) in the Chair.]</p>"
                "<p><strong>Miss Rachel Ong</strong>: "
                "I welcome the Minister's assurance on accountability.</p>"
            ),
        },
        {
            "sectionType": "OA",
            "title": "Oral Answers - Health",
            "content": (
                "<p>13 <strong>Mr Louis Ng Kok Kwang</strong> asked the Minister for Health "
                "whether the Ministry will review subsidies for chronic care.</p>"
            ),
        },
        {
            "sectionType": "WA",
            "title": "Written Answers",
            "content": (
                "<p><strong>The Minister for Health (Mr Ong Ye Kung)</strong>: "
                "The Ministry provides means-tested subsidies through various schemes.</p>"
            ),
        },
    ],
}


@pytest.fixture(scope="module")
def parsed():
    df_att, df_ptba, df_speech, source_url, parliament_no, sitting_dt = parse_one_sitting(
        SAMPLE_SITTING
    )
    return {
        "att": df_att,
        "ptba": df_ptba,
        "speech": df_speech,
        "source_url": source_url,
        "parliament_no": parliament_no,
        "sitting_dt": sitting_dt,
    }


# ---------------- top-level metadata ----------------

def test_metadata(parsed):
    assert parsed["parliament_no"] == 14
    assert parsed["sitting_dt"] == date(2025, 1, 7)
    assert "sittingDate=07-01-2025" in parsed["source_url"]


def test_infer_parliament_no_variants():
    assert infer_parliament_no_from_metadata({"metadata": {"parlimentNO": "13"}}) == 13
    assert infer_parliament_no_from_metadata({"metadata": {"parlimentNO": 13}}) == 13
    assert infer_parliament_no_from_metadata({"metadata": {}}) is None
    assert infer_parliament_no_from_metadata({"metadata": {"parlimentNO": "x"}}) is None


# ---------------- ptba_overlaps_sitting (pure) ----------------

def test_ptba_overlaps_sitting_boundary():
    dt = date(2025, 1, 7)
    assert ptba_overlaps_sitting({"from": "7 Jan", "to": "9 Jan"}, dt, 2025) is True
    assert ptba_overlaps_sitting({"from": "5 Jan", "to": "7 Jan"}, dt, 2025) is True  # end boundary
    assert ptba_overlaps_sitting({"from": "8 Jan", "to": "9 Jan"}, dt, 2025) is False
    assert ptba_overlaps_sitting({"from": None, "to": "9 Jan"}, dt, 2025) is False


def test_ptba_cross_year_wrap():
    # from 30 Dec to 2 Jan should wrap into the next year and cover 1 Jan.
    dt = date(2026, 1, 1)
    assert ptba_overlaps_sitting({"from": "30 Dec", "to": "2 Jan"}, dt, 2025) is True


# ---------------- attendance ----------------

def test_attendance_rowcount_skips_blank(parsed):
    # 6 real MPs; blank separator row dropped.
    assert len(parsed["att"]) == 6


def test_attendance_speaker_dimensions(parsed):
    att = parsed["att"].set_index("mp_name_raw")
    sp = att.loc["Mr SPEAKER (Mr Seah Kian Peng (Marine Parade))."]
    assert sp["dim_is_speaker"] == 1
    assert sp["dim_is_deputy_speaker"] == 0
    assert sp["mp_name_cleaned"] == "Seah Kian Peng"


def test_attendance_deputy_speaker_cleaned_name(parsed):
    # Bug-fix coverage in the integration path: nested-name Deputy Speaker line
    # must clean to the person's name, not a malformed constituency-leaking string.
    att = parsed["att"].set_index("mp_name_raw")
    dep = att.loc["Mr Deputy Speaker (Mr Christopher de Souza (Holland-Bukit Timah))."]
    assert dep["dim_is_deputy_speaker"] == 1
    assert dep["dim_is_speaker"] == 0
    assert dep["mp_name_cleaned"] == "Christopher de Souza"


def test_attendance_presence_flag(parsed):
    att = parsed["att"].set_index("mp_name_raw")
    assert att.loc["Miss Rachel Ong (West Coast)."]["dim_is_present"] == 1
    assert att.loc["Ms Sylvia Lim (Aljunied)."]["dim_is_present"] == 0


# ---------------- PTBA ----------------

def test_ptba_only_overlapping_rows(parsed):
    ptba = parsed["ptba"]
    assert len(ptba) == 1
    row = ptba.iloc[0]
    assert row["mp_name_raw"] == "Ms Sylvia Lim"
    assert row["mp_name_cleaned"] == "Sylvia Lim"


# ---------------- speeches ----------------

def test_speech_rowcount(parsed):
    assert len(parsed["speech"]) == 4


def test_speech_row1_chair_is_speaker(parsed):
    r = parsed["speech"].iloc[0]
    assert r["mp_name_raw"] == "Mr Chan Chun Sing"
    assert r["mp_name_fuzzy_matched"] == "Chan Chun Sing"
    assert r["dim_speaker"] == "speaker"
    assert r["chair_name_raw"] == "Seah Kian Peng"
    assert r["dim_is_oral_speech"] == 1
    # Continuation paragraph merged into the same speech.
    assert "public trust" in r["speech_details"]
    assert "strengthen accountability" in r["speech_details"]


def test_speech_row2_chair_flipped_to_deputy(parsed):
    r = parsed["speech"].iloc[1]
    assert r["mp_name_raw"] == "Miss Rachel Ong"
    assert r["mp_name_fuzzy_matched"] == "Rachel Ong"
    # The [... in the Chair.] marker flipped the tracked chair.
    assert r["dim_speaker"] == "deputy_speaker"
    assert r["chair_name_raw"] == "Christopher de Souza"
    assert r["dim_is_oral_speech"] == 1


def test_speech_row3_question_paper_item(parsed):
    r = parsed["speech"].iloc[2]
    assert r["section_type"] == "OA"
    assert r["mp_name_raw"] == "Mr Louis Ng Kok Kwang"
    # Question-Time listing: not an oral speech, but flagged as oral-answer question.
    assert r["dim_is_oral_speech"] == 0
    assert r["dim_is_question_for_oral_answer"] == 1


def test_speech_row4_written_answer(parsed):
    r = parsed["speech"].iloc[3]
    assert r["section_type"] == "WA"
    assert r["dim_is_written_answer_to_questions"] == 1
    assert r["dim_is_oral_speech"] == 0
    # Written sections suppress chair attribution. pandas represents missing
    # values as NaN (object columns may keep None), so test with isna().
    assert pd.isna(r["dim_speaker"])
    assert pd.isna(r["chair_name_raw"])


def test_row_nums_are_unique_and_sequential(parsed):
    row_nums = parsed["speech"]["row_num"].tolist()
    assert row_nums == [1, 2, 3, 4]


# ---------------- empty payload robustness ----------------

def test_parse_empty_sections():
    data = {
        "metadata": {"sittingDate": "07-01-2025"},
        "attendanceList": [{"mpName": "Mr Chan Chun Sing (Tanjong Pagar).", "attendance": True}],
        "ptbaList": [],
        "takesSectionVOList": [],
    }
    df_att, df_ptba, df_speech, _url, _pno, _dt = parse_one_sitting(data)
    assert len(df_att) == 1
    assert isinstance(df_ptba, pd.DataFrame) and df_ptba.empty
    assert isinstance(df_speech, pd.DataFrame) and df_speech.empty
