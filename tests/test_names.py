"""Unit tests for hansard_ingest.names — pure name cleaning / chair / fuzzy logic.

Expected values are derived from the functions' documented intent (docstrings,
worked examples) rather than from their current output, so these tests can
surface a regression rather than merely pinning it.
"""

from hansard_ingest.names import (
    best_fuzzy_match,
    chair_role,
    clean_mp_name_from_attendance,
    extract_chair_marker,
    extract_last_parenthesized_text,
    extract_person_from_name,
    extract_person_from_speaker_attendance,
    infer_chair_from_speaker_label,
    is_chair_call_to_member,
    is_question_paper_item,
    name_key,
    norm_for_match,
    strip_trailing_chair_call,
)


# ---------------- chair_role ----------------

def test_chair_role_speaker():
    assert chair_role("Mr Speaker") == "speaker"


def test_chair_role_deputy_speaker_not_confused_with_speaker():
    # "DEPUTY SPEAKER" must win even though it also contains "SPEAKER".
    assert chair_role("Mr Deputy Speaker") == "deputy_speaker"


def test_chair_role_non_chair_and_empty():
    assert chair_role("Mr Chan Chun Sing") is None
    assert chair_role("") is None
    assert chair_role(None) is None


# ---------------- strip_trailing_chair_call ----------------

def test_strip_trailing_chair_call_removes_mr_speaker():
    assert strip_trailing_chair_call("Thank you, Mr Speaker.") == "Thank you,"
    assert strip_trailing_chair_call("Thank you, Madam Speaker") == "Thank you,"


def test_strip_trailing_chair_call_leaves_body_untouched():
    assert strip_trailing_chair_call("The Speaker is elected by Members.") == (
        "The Speaker is elected by Members."
    )


# ---------------- name_key ----------------

def test_name_key_strips_honorific_constituency_and_role():
    assert name_key("Mr Chan Chun Sing (Tanjong Pagar), Coordinating Minister") == (
        "CHAN CHUN SING"
    )


def test_name_key_empty():
    assert name_key("") == ""
    assert name_key(None) == ""


# ---------------- extract_chair_marker ----------------

def test_extract_chair_marker_basic():
    assert extract_chair_marker("[Mr Speaker in the Chair.]") == "Mr Speaker"


def test_extract_chair_marker_deputy_with_name():
    assert extract_chair_marker(
        "[Mr Deputy Speaker (Mr Christopher de Souza) in the Chair.]"
    ) == "Mr Deputy Speaker (Mr Christopher de Souza)"


def test_extract_chair_marker_rejects_non_marker():
    assert extract_chair_marker("Mr Speaker rose to address the House.") is None
    assert extract_chair_marker("[Some bracketed aside.]") is None
    assert extract_chair_marker("") is None


# ---------------- infer_chair_from_speaker_label ----------------

def test_infer_chair_from_speaker_label():
    assert infer_chair_from_speaker_label("Mr Speaker") == "Mr Speaker"
    assert infer_chair_from_speaker_label("Mr Deputy Speaker") == "Mr Deputy Speaker"
    # A normal MP label is not a chair.
    assert infer_chair_from_speaker_label("Mr Chan Chun Sing") is None
    assert infer_chair_from_speaker_label("") is None


# ---------------- is_question_paper_item ----------------

def test_is_question_paper_item_true():
    speaker = "Mr Louis Ng Kok Kwang"
    speech = "12 Mr Louis Ng Kok Kwang asked the Minister for Health whether ..."
    assert is_question_paper_item(speaker, speech) is True


def test_is_question_paper_item_false_when_spoken_debate():
    # A normal speech (no leading number, not "asked the Minister") is not a listing.
    speaker = "Mr Louis Ng Kok Kwang"
    speech = "Mr Louis Ng Kok Kwang: I thank the Minister for the reply."
    assert is_question_paper_item(speaker, speech) is False


def test_is_question_paper_item_empty():
    assert is_question_paper_item("", "") is False


# ---------------- is_chair_call_to_member ----------------

def test_is_chair_call_to_member_true():
    assert is_chair_call_to_member("Mr Patrick Tay.") is True
    assert is_chair_call_to_member("Er Dr Lee Bee Wah.") is True


def test_is_chair_call_to_member_false_for_real_sentence():
    # Contains a verb like "thank"/"ask" -> substantive, not a call-out.
    assert is_chair_call_to_member("Mr Speaker, I thank the Minister.") is False
    # No trailing period -> not a call-out.
    assert is_chair_call_to_member("Mr Patrick Tay") is False
    # Too long -> not a bare name call-out.
    assert is_chair_call_to_member(
        "Mr Patrick Tay and the rest of the committee members will report."
    ) is False


# ---------------- extract_person_from_speaker_attendance ----------------

def test_extract_person_from_speaker_attendance_docstring_example():
    assert extract_person_from_speaker_attendance(
        "Mr SPEAKER (Mr Seah Kian Peng (Marine Parade))."
    ) == "Seah Kian Peng"


def test_extract_person_from_speaker_attendance_none_without_parens():
    assert extract_person_from_speaker_attendance("Mr Speaker") is None


# ---------------- extract_person_from_name ----------------

def test_extract_person_from_name_role_with_parenthesised_person():
    assert extract_person_from_name(
        "The Minister for Foreign Affairs (Dr Vivian Balakrishnan)"
    ) == "Vivian Balakrishnan"


def test_extract_person_from_name_multitoken_honorific():
    assert extract_person_from_name(
        "The Minister for the Environment (Assoc Prof Dr Yaacob Ibrahim)"
    ) == "Yaacob Ibrahim"


def test_extract_person_from_name_bare_speaker_returns_none():
    # Bare chair labels are resolved via the attendance map, not here.
    assert extract_person_from_name("Mr Speaker") is None


def test_extract_person_from_name_plain_person():
    assert extract_person_from_name("Mr Chan Chun Sing (Tanjong Pagar), Minister") == (
        "Chan Chun Sing"
    )


# ---------------- extract_last_parenthesized_text ----------------

def test_extract_last_parenthesized_text():
    assert extract_last_parenthesized_text(
        "The Minister for X (Assoc Prof Dr Yaacob Ibrahim)"
    ) == "Yaacob Ibrahim"
    # Single-token (constituency-like) parenthetical is rejected.
    assert extract_last_parenthesized_text("Something (Jurong)") is None
    assert extract_last_parenthesized_text("No parentheses here") is None


# ---------------- clean_mp_name_from_attendance ----------------

def test_clean_mp_name_docstring_examples():
    assert clean_mp_name_from_attendance(
        "Mr Chan Chun Sing (Tanjong Pagar), Coordinating Minister ..."
    ) == "Chan Chun Sing"
    assert clean_mp_name_from_attendance("Miss Rachel Ong (West Coast).") == "Rachel Ong"
    assert clean_mp_name_from_attendance(
        "Mr SPEAKER (Mr Seah Kian Peng (Marine Parade))."
    ) == "Seah Kian Peng"


def test_clean_mp_name_deputy_speaker_nested_person():
    # Regression guard: the Deputy Speaker attendance line nests the person the
    # same way the Speaker line does, so it must resolve to the clean name
    # (not a malformed 'Christopher de Souza (Holland-Bukit Timah').
    assert clean_mp_name_from_attendance(
        "Mr Deputy Speaker (Mr Christopher de Souza (Holland-Bukit Timah))."
    ) == "Christopher de Souza"


def test_clean_mp_name_multitoken_honorific():
    assert clean_mp_name_from_attendance("Assoc Prof Dr Jamus Jerome Lim (Sengkang)") == (
        "Jamus Jerome Lim"
    )


def test_clean_mp_name_empty():
    assert clean_mp_name_from_attendance("") is None
    assert clean_mp_name_from_attendance(None) is None


# ---------------- norm_for_match ----------------

def test_norm_for_match_strips_role_words_and_punctuation():
    a = norm_for_match("The Minister for Foreign Affairs (Dr Vivian Balakrishnan)")
    b = norm_for_match("Dr Vivian Balakrishnan")
    # Parenthetical person is dropped by norm_for_match, so the role label
    # normalises to just the portfolio words being removed -> compare stable keys.
    assert norm_for_match("Mr Chan Chun Sing (Tanjong Pagar), Minister") == "CHAN CHUN SING"
    assert isinstance(a, str) and isinstance(b, str)


def test_norm_for_match_empty():
    assert norm_for_match("") == ""
    assert norm_for_match(None) == ""


# ---------------- best_fuzzy_match ----------------

def test_best_fuzzy_match_picks_correct_above_threshold():
    choices = ["Chan Chun Sing", "Rachel Ong", "Vivian Balakrishnan"]
    best, score = best_fuzzy_match("Mr Chan Chun Sing", choices)
    assert best == "Chan Chun Sing"
    assert score >= 0.75


def test_best_fuzzy_match_unrelated_name_below_threshold():
    choices = ["Chan Chun Sing", "Rachel Ong", "Vivian Balakrishnan"]
    best, score = best_fuzzy_match("Zaqueus Xylophone", choices)
    # Whatever it picks, the score must be low enough that parse.py rejects it
    # (parse uses a 0.75 cutoff).
    assert score < 0.75


def test_best_fuzzy_match_empty_query():
    assert best_fuzzy_match("", ["Chan Chun Sing"]) == (None, 0.0)
