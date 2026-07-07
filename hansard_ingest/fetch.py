"""HTTP fetch for the public Hansard JSON endpoint.

Uses a shared :class:`requests.Session` with automatic retries (with
exponential backoff) so transient upstream errors and rate limits don't
fail a run outright.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import BASE_URL

USER_AGENT = "sg-hansard-ingest (+https://github.com/toshtxg/sg-hansard)"


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


# Module-level session reused across all per-day fetches.
_SESSION = _build_session()


def fetch_hansard_json(sitting_ddmmyyyy: str) -> dict:
    """Fetch the raw Hansard JSON for a single sitting date.

    The Parliament API expects ``DD-MM-YYYY``. Non-sitting days return an
    empty payload, which the parser handles by emitting empty DataFrames.
    """
    url = f"{BASE_URL}?sittingDate={sitting_ddmmyyyy}"
    r = _SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.json()
