"""HTTP fetch for the public Hansard JSON endpoint.

Uses a shared :class:`requests.Session` with automatic retries (with
exponential backoff) so transient upstream errors and rate limits don't
fail a run outright.

Upstream signals "there is no Hansard report for this date" with an HTTP
500 carrying a JSON error envelope, *not* with an empty 200 — see
:class:`NoSittingReport` for why that distinction has to be made here.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import BASE_URL

USER_AGENT = "sg-hansard-ingest (+https://github.com/toshtxg/sg-hansard)"


class NoSittingReport(Exception):
    """Upstream has no Hansard report for the requested date.

    As of 2026-08 ``sprs.parl.gov.sg`` answers a date with no sitting with::

        HTTP 500  {"errorCode":500,"description":"Unable to process the request..."}

    It previously returned a payload the parser could read. Treating that 500
    as a transient fault (the old behaviour) made every non-sitting day look
    like an upstream failure: runs reported ``upstream_failures=21`` during
    recess, spent ~11 minutes in retry backoff, and defeated the total-blackout
    alarm, which relies on separating "reachable but nothing to report" from
    "unreachable".

    The envelope is generic, so a genuine server fault is indistinguishable
    from an empty date *on a single request*. ``upstream_has_report()`` is the
    discriminator: it re-queries a date known to have a report.
    """


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        # 500 is deliberately absent: upstream uses it as its "no report for
        # this date" response, so retrying it burns ~30s of backoff per
        # non-sitting day for a result that will never change. Genuine 500s
        # are re-scanned by the next run's rolling lookback window instead.
        status_forcelist=[429, 502, 503, 504],
        # urllib3 excludes POST by default because POST is not idempotent in
        # general. This one is: it carries a read-only lookup that upstream
        # moved from GET to POST, so retrying it is safe and worth opting into.
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


# Module-level session reused across all per-day fetches.
_SESSION = _build_session()


def _is_no_report_envelope(r: requests.Response) -> bool:
    """True if a 500 response is upstream's "no report for this date" marker."""
    try:
        body = r.json()
    except ValueError:
        # A real fault (gateway HTML, truncated body) — not the marker.
        return False
    return isinstance(body, dict) and body.get("errorCode") == 500


def fetch_hansard_json(sitting_ddmmyyyy: str) -> dict:
    """Fetch the raw Hansard JSON for a single sitting date.

    The Parliament API expects ``DD-MM-YYYY``, sent as a JSON body on a POST:
    ``{"sittingDate": "04-08-2026"}``.

    It previously served the same lookup as ``GET ?sittingDate=``. That form
    was retired mid-August 2026 and now answers *every* date with the generic
    500 envelope below — including sittings already in the database. Because
    that envelope is also how upstream says "no sitting", the pipeline read a
    dead endpoint as three weeks of recess and kept reporting success.

    Raises :class:`NoSittingReport` when upstream reports no Hansard for the
    date, and :class:`requests.exceptions.RequestException` for real transport
    or server faults. Callers must handle the two differently: the first is an
    ordinary recess day, the second is worth retrying.
    """
    r = _SESSION.post(BASE_URL, json={"sittingDate": sitting_ddmmyyyy}, timeout=30)
    if r.status_code == 500 and _is_no_report_envelope(r):
        raise NoSittingReport(sitting_ddmmyyyy)
    r.raise_for_status()
    return r.json()


def upstream_has_report(sitting_ddmmyyyy: str) -> bool:
    """Probe a date known to have a report, to test whether upstream is sane.

    Because the "no report" envelope is generic, a run where *every* day came
    back empty is ambiguous: it is either a recess or a broken endpoint. Asking
    for a date we have already ingested settles it — if that comes back empty
    too, upstream is lying and the run is a blackout, not a quiet week.
    """
    try:
        fetch_hansard_json(sitting_ddmmyyyy)
        return True
    except Exception:
        return False
