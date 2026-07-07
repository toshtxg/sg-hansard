"""Unit tests for the PURE helpers in hansard_ingest.ai_speech_summary.

Network / AI-gated paths (summarize_row, _post_with_backoff, _call_responses_api)
are intentionally NOT exercised here.
"""

from hansard_ingest.ai_speech_summary import (
    SUMMARY_VERSION,
    build_summary_update,
    build_user_content,
    extract_output_text,
    infer_role_from_label,
    needs_summary,
    parse_summary_output,
    short_circuit_summary,
)


# ---------------- needs_summary ----------------

def test_needs_summary_true_when_missing_or_stale():
    assert needs_summary(None, SUMMARY_VERSION) is True
    assert needs_summary("", SUMMARY_VERSION) is True
    assert needs_summary("a one liner", "v1") is True


def test_needs_summary_false_when_current():
    assert needs_summary("a one liner", SUMMARY_VERSION) is False


# ---------------- infer_role_from_label ----------------

def test_infer_role_from_label():
    assert infer_role_from_label("Mr Speaker") == "chair"
    assert infer_role_from_label("Mr Deputy Speaker") == "chair"
    assert infer_role_from_label("The Chairman") == "chair"
    assert infer_role_from_label("Mr Chan Chun Sing") == ""
    assert infer_role_from_label("") == ""


# ---------------- short_circuit_summary ----------------

def test_short_circuit_for_short_text():
    out = short_circuit_summary("Aye.", {})
    assert out is not None
    assert out["segment_type"] in {"procedural", "other"}
    assert out["themes"] == []
    assert out["key_claims"] == []


def test_short_circuit_for_short_chair_line():
    # Chair role short-circuits for lines under 180 chars.
    out = short_circuit_summary("Mr Patrick Tay.", {"role": "chair"})
    assert out is not None


def test_no_short_circuit_for_long_substantive_text():
    text = (
        "I rise to support this Bill because it addresses the long-standing "
        "concerns raised by residents in my constituency about public transport "
        "reliability and affordability over the past several years."
    )
    assert short_circuit_summary(text, {}) is None


# ---------------- build_user_content ----------------

def test_build_user_content_includes_metadata_and_text():
    content = build_user_content(
        "Some speech text.",
        {"speaker_name": "Chan Chun Sing", "role": "", "sitting_date": "2025-01-07"},
    )
    assert "speaker_name: Chan Chun Sing" in content
    assert "sitting_date: 2025-01-07" in content
    assert "Some speech text." in content
    # Empty role field is omitted.
    assert "role:" not in content


# ---------------- parse_summary_output / _validate_payload ----------------

def test_parse_summary_output_valid():
    raw = (
        '{"segment_type": "question", "one_liner": "Asks about bus reliability", '
        '"themes": ["transport"], "key_claims": ["buses are late"]}'
    )
    out = parse_summary_output(raw)
    assert out == {
        "segment_type": "question",
        "one_liner": "Asks about bus reliability",
        "themes": ["transport"],
        "key_claims": ["buses are late"],
    }


def test_parse_summary_output_rejects_bad_segment_type():
    raw = (
        '{"segment_type": "nonsense", "one_liner": "x", "themes": [], "key_claims": []}'
    )
    assert parse_summary_output(raw) is None


def test_parse_summary_output_rejects_invalid_json():
    assert parse_summary_output("not json") is None
    assert parse_summary_output("") is None


def test_parse_summary_output_trims_and_caps():
    long_one_liner = " ".join(["word"] * 50)  # 50 words, capped at 30
    themes = [f"theme{i}" for i in range(10)]  # capped at 6
    claims = [f"claim {i}" for i in range(10)]  # capped at 5
    import json
    raw = json.dumps({
        "segment_type": "statement",
        "one_liner": long_one_liner,
        "themes": themes,
        "key_claims": claims,
    })
    out = parse_summary_output(raw)
    assert len(out["one_liner"].split()) == 30
    assert len(out["themes"]) == 6
    assert len(out["key_claims"]) == 5


# ---------------- build_summary_update ----------------

def test_build_summary_update_procedural_nulls_content():
    payload = {
        "segment_type": "procedural",
        "one_liner": "Calls next speaker",
        "themes": ["order"],
        "key_claims": ["x"],
    }
    out = build_summary_update(payload)
    assert out["segment_type"] == "procedural"
    assert out["one_liner"] is None
    assert out["themes"] == []
    assert out["key_claims"] == []
    assert out["summary_version"] == SUMMARY_VERSION
    assert "summarized_at" in out


def test_build_summary_update_substantive_keeps_content():
    payload = {
        "segment_type": "answer",
        "one_liner": "Explains new policy",
        "themes": ["policy"],
        "key_claims": ["policy starts in 2026"],
    }
    out = build_summary_update(payload)
    assert out["one_liner"] == "Explains new policy"
    assert out["themes"] == ["policy"]
    assert out["summary_version"] == SUMMARY_VERSION


# ---------------- extract_output_text ----------------

def test_extract_output_text_direct_field():
    assert extract_output_text({"output_text": "hello"}) == "hello"


def test_extract_output_text_nested_output():
    data = {
        "output": [
            {"content": [{"type": "output_text", "text": "nested value"}]}
        ]
    }
    assert extract_output_text(data) == "nested value"
