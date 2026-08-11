"""Tests for how a run classifies its own outcome.

These cover the orchestration-level consequence of the 2026-07/08 stall: a
window where upstream answers "no Hansard" for every day must be reported as a
recess, and must be distinguishable from upstream having broken. Both look
identical in the fetch loop; only the control probe separates them.
"""

from datetime import date

import pytest

import hansard_ingest.main as main
from hansard_ingest.fetch import NoSittingReport


def _quiet_run(monkeypatch, **overrides):
    """Configure ingest() for an offline, no-DB, no-AI run."""
    defaults = {
        "SKIP_DB": True,
        "LOG_RUNS": False,
        "AI_ENABLED": False,
        "RUN_DATE": "",
        "START_DATE_ISO": "2026-05-08",
        "END_DATE_ISO": "2026-05-10",
        "MAX_DAYS_PER_RUN": 0,
        "FETCH_SLEEP_SECS": 0,
        "DEBUG": False,
        "ALERT_ON_TOTAL_BLACKOUT": False,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(main, name, value)


def test_no_report_days_count_as_recess_not_failure(monkeypatch, capsys):
    """The regression itself: three empty days, zero failures.

    Before the fix these three days were counted as upstream_failures, which
    is what let a dead pipeline report success for two weeks.
    """
    _quiet_run(monkeypatch)
    monkeypatch.setattr(
        main, "fetch_hansard_json", lambda _: (_ for _ in ()).throw(NoSittingReport("x"))
    )

    main.ingest()

    out = capsys.readouterr().out
    assert "no_sitting_days=3" in out
    assert "upstream_failures=0" in out
    assert "hard_failures=0" in out


def test_no_report_day_never_reaches_the_parser(monkeypatch):
    """parse_one_sitting() raises KeyError on a payload with no metadata block,
    so routing a recess day through it would turn every run red."""
    _quiet_run(monkeypatch)
    monkeypatch.setattr(
        main, "fetch_hansard_json", lambda _: (_ for _ in ()).throw(NoSittingReport("x"))
    )

    def _explode(_):
        raise AssertionError("parser must not be called for a no-report day")

    monkeypatch.setattr(main, "parse_one_sitting", _explode)

    main.ingest()


def test_transient_failures_are_still_reported(monkeypatch, capsys):
    """A genuine fault must not be laundered into the recess bucket."""
    import requests

    _quiet_run(monkeypatch)
    monkeypatch.setattr(
        main,
        "fetch_hansard_json",
        lambda _: (_ for _ in ()).throw(requests.exceptions.ConnectionError("boom")),
    )

    main.ingest()

    out = capsys.readouterr().out
    assert "upstream_failures=3" in out
    assert "no_sitting_days=0" in out


def test_blackout_alarm_fires_when_control_probe_fails(monkeypatch, capsys):
    """Every day empty AND a known sitting now empty => upstream is broken."""
    _quiet_run(monkeypatch, SKIP_DB=False, ALERT_ON_TOTAL_BLACKOUT=True)
    monkeypatch.setattr(main, "supabase_client", lambda: object())
    monkeypatch.setattr(main, "get_latest_sitting", lambda _: date(2026, 7, 7))
    monkeypatch.setattr(
        main, "fetch_hansard_json", lambda _: (_ for _ in ()).throw(NoSittingReport("x"))
    )
    monkeypatch.setattr(main, "upstream_has_report", lambda _: False)

    with pytest.raises(SystemExit) as exc:
        main.ingest()

    assert exc.value.code == 1
    assert "ALERT: total upstream blackout" in capsys.readouterr().out


def test_recess_does_not_fire_the_blackout_alarm(monkeypatch, capsys):
    """Same empty window, but the control date still serves: stay green.

    This is the case that makes ALERT_ON_TOTAL_BLACKOUT safe to enable — the
    old logic would have paged every day of a recess.
    """
    _quiet_run(monkeypatch, SKIP_DB=False, ALERT_ON_TOTAL_BLACKOUT=True)
    monkeypatch.setattr(main, "supabase_client", lambda: object())
    monkeypatch.setattr(main, "get_latest_sitting", lambda _: date(2026, 7, 7))
    monkeypatch.setattr(
        main, "fetch_hansard_json", lambda _: (_ for _ in ()).throw(NoSittingReport("x"))
    )
    monkeypatch.setattr(main, "upstream_has_report", lambda _: True)

    main.ingest()  # must not raise SystemExit

    assert "recess, not an outage" in capsys.readouterr().out
