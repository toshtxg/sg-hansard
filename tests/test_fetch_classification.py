"""Tests for how upstream responses are classified.

Regression guard for the 2026-07/08 silent stall: sprs.parl.gov.sg started
answering non-sitting dates with HTTP 500 instead of a readable payload, so
every recess day was counted as a transient upstream failure. Runs reported
``upstream_failures=21``, ingested nothing, wrote nothing to Supabase, and
still went green for two weeks.

The distinction being guarded here is three-way: a report, a definitive "no
report", and a genuine fault. Collapsing the middle case into either of the
others is what caused the outage to be invisible.
"""

import pytest
import requests

import hansard_ingest.fetch as fetch
from hansard_ingest.fetch import NoSittingReport


class FakeResponse:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON object could be decoded")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Server Error")


def _patch_post(monkeypatch, response):
    monkeypatch.setattr(fetch._SESSION, "post", lambda *a, **k: response)


def test_no_report_envelope_raises_no_sitting_report(monkeypatch):
    """The exact envelope upstream returns for a date with no sitting."""
    _patch_post(
        monkeypatch,
        FakeResponse(
            500,
            {
                "errorCode": 500,
                "description": "Unable to process the request. Please try after sometime.",
            },
        ),
    )
    with pytest.raises(NoSittingReport):
        fetch.fetch_hansard_json("08-05-2026")


def test_no_sitting_report_is_not_a_request_exception():
    """main.ingest() catches these in separate branches; overlapping types
    would let a recess day fall through to the transient-failure handler."""
    assert not issubclass(NoSittingReport, requests.exceptions.RequestException)


def test_html_error_page_is_a_transient_failure(monkeypatch):
    """A real 5xx (gateway HTML, not the JSON envelope) must stay retryable."""
    _patch_post(
        monkeypatch,
        FakeResponse(502, payload=None, text="<html><body>502 Bad Gateway</body></html>"),
    )
    with pytest.raises(requests.exceptions.RequestException):
        fetch.fetch_hansard_json("08-05-2026")


def test_500_without_the_envelope_is_a_transient_failure(monkeypatch):
    """A 500 carrying different JSON is a fault, not a 'no report' marker."""
    _patch_post(monkeypatch, FakeResponse(500, {"error": "database unavailable"}))
    with pytest.raises(requests.exceptions.RequestException):
        fetch.fetch_hansard_json("08-05-2026")


def test_successful_payload_is_returned(monkeypatch):
    payload = {"metadata": {"sittingDate": "07-05-2026", "parlimentNO": 15}}
    _patch_post(monkeypatch, FakeResponse(200, payload))
    assert fetch.fetch_hansard_json("07-05-2026") == payload


def test_500_is_not_retried_by_the_session():
    """500 must stay out of status_forcelist: upstream uses it as a normal
    answer, and retrying it cost ~30s of backoff per non-sitting day."""
    retry = fetch._SESSION.get_adapter("https://sprs.parl.gov.sg").max_retries
    assert 500 not in retry.status_forcelist
    for code in (429, 502, 503, 504):
        assert code in retry.status_forcelist


def test_post_is_retryable():
    """The lookup is a POST but is read-only, so it must not be excluded from
    retries the way urllib3 excludes POST by default."""
    retry = fetch._SESSION.get_adapter("https://sprs.parl.gov.sg").max_retries
    assert "POST" in {m.upper() for m in retry.allowed_methods}


def test_lookup_is_posted_as_json_body():
    """Upstream retired ``GET ?sittingDate=`` in August 2026: it now answers
    every date, sitting or not, with the generic 500 envelope. The date must go
    out as a JSON body on a POST or the pipeline silently reads live sittings
    as recess."""
    seen = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        seen["url"] = url
        seen["json"] = json
        return FakeResponse(200, {"metadata": {"sittingDate": "04-08-2026"}})

    import hansard_ingest.fetch as f

    original = f._SESSION.post
    f._SESSION.post = fake_post
    try:
        f.fetch_hansard_json("04-08-2026")
    finally:
        f._SESSION.post = original

    assert seen["json"] == {"sittingDate": "04-08-2026"}
    assert "?sittingDate=" not in seen["url"]


# ---- Blackout control probe -------------------------------------------------


def test_control_probe_false_when_known_sitting_reports_empty(monkeypatch):
    """A date already in the database coming back 'no report' means upstream
    is broken, not that Parliament is in recess."""
    def _raise(_):
        raise NoSittingReport("07-05-2026")

    monkeypatch.setattr(fetch, "fetch_hansard_json", _raise)
    assert fetch.upstream_has_report("07-05-2026") is False


def test_control_probe_true_when_known_sitting_still_serves(monkeypatch):
    monkeypatch.setattr(fetch, "fetch_hansard_json", lambda _: {"metadata": {}})
    assert fetch.upstream_has_report("07-05-2026") is True
