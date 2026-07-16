"""Tests for transient DB error handling in the upsert path.

Regression guard for the 2026-07-15 ingest failure, where a one-off Postgres
statement timeout (SQLSTATE 57014) on a hansard_speeches upsert turned the
whole scheduled run red even though the day self-heals on the next lookback.
"""

import hansard_ingest.db as db


def _no_sleep(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda *_: None)


def test_statement_timeout_is_transient():
    err = Exception(
        "{'message': 'canceling statement due to statement timeout', "
        "'code': '57014', 'hint': None, 'details': None}"
    )
    assert db._is_transient_db_error(err) is True


def test_dropped_connection_is_transient():
    assert db._is_transient_db_error(Exception("server closed the connection unexpectedly")) is True


def test_data_error_is_not_transient():
    assert db._is_transient_db_error(Exception("duplicate key value violates unique constraint")) is False


def test_retry_recovers_from_transient_blip(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    class Q:
        def execute(self):
            calls["n"] += 1
            if calls["n"] < 2:
                raise Exception("canceling statement due to statement timeout (57014)")
            return "ok"

    assert db._execute_with_retry(lambda: Q()) == "ok"
    assert calls["n"] == 2  # failed once, succeeded on retry


def test_non_transient_error_raises_immediately(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    class Q:
        def execute(self):
            calls["n"] += 1
            raise Exception("duplicate key value violates unique constraint")

    try:
        db._execute_with_retry(lambda: Q())
        assert False, "expected the error to propagate"
    except Exception as e:
        assert "duplicate key" in str(e)
    assert calls["n"] == 1  # no retries for a real data error


def test_persistent_transient_error_exhausts_retries_then_raises(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    class Q:
        def execute(self):
            calls["n"] += 1
            raise Exception("statement timeout")

    try:
        db._execute_with_retry(lambda: Q())
        assert False, "expected the error to propagate after exhausting retries"
    except Exception as e:
        assert "statement timeout" in str(e)
    assert calls["n"] == db.DB_MAX_RETRIES
