"""
Shared HTTP session for calling Groq's API with automatic retry on rate
limits (429) and transient server errors. Groq's free tier has real
requests-per-minute limits, and a single 429 shouldn't take down a whole
pipeline run - especially now that topup rounds mean more calls per run.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
_retry = Retry(
    total=6,
    backoff_factor=5,  # 5s, 10s, 20s, 40s, 80s, 160s - real breathing room for a free-tier limit to clear
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
    allowed_methods=["POST"],  # POST isn't idempotent by default in urllib3 - opt in explicitly
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def groq_post(url: str, headers: dict, json_body: dict, timeout: int = 120) -> requests.Response:
    """POST to Groq with retry/backoff already applied. Raises on final failure."""
    resp = _session.post(url, headers=headers, json=json_body, timeout=timeout)
    resp.raise_for_status()
    return resp
