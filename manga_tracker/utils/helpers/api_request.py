"""
manga_tracker/utils/helpers/api_request.py

Shared utility for making HTTP API requests with standardised retry logic.
Use this for ALL raw HTTP calls (requests.get / post / patch) across pipelines.

Not intended for Python SDK-based API clients (e.g. HubSpot Python client lib).

Usage:
    from manga_tracker.utils.helpers.api_request import make_api_request

    response = make_api_request(
        method="GET",
        url="https://data-eu.mixpanel.com/api/2.0/export",
        auth=HTTPBasicAuth(user, secret),
        params={"from_date": "2026-01-01", ...},
        timeout=600,
    )
"""

from typing import Optional

import requests
from requests.auth import AuthBase
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# ---------------------------------------------------------------------------
# Constants — tweak here to change retry behavior across all pipelines making raw HTTP requests
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 3  # 1 initial attempt + 2 retries (matches Mage setting)
_WAIT_MIN = 2  # seconds before first retry
_WAIT_MAX = 60  # cap on wait between retries
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class APIRequestError(Exception):
    """
    Raised when an API request fails after all retry attempts are exhausted,
    or immediately when a non-retryable HTTP error is returned.

    Carrying status_code and response_text as typed attributes — rather than
    embedding them in the message string — lets callers inspect them directly
    (e.g. `if e.status_code == 401`) without fragile string parsing. It also
    makes Slack alerts and Mage logs more actionable.

    Attributes:
        status_code (int | None): HTTP status code, if available.
        response_text (str | None): Raw response body, if available.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_text: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class _RetryableAPIError(Exception):
    """
    Internal signal exception used to trigger tenacity retries.
    Never raised outside of this module.

    Using a dedicated private exception — rather than retrying on all exceptions
    or on broad base classes — gives us precise control: tenacity only retries
    when we explicitly decide a failure is transient and worth retrying. This
    prevents retrying on things like ValueError or bad input that will never
    recover regardless of how many attempts are made.
    """

    pass


# ---------------------------------------------------------------------------
# Internal retry executor — module-level so it is independently testable
#
# Intentionally not nested inside make_api_request() for two reasons:
#   1. Testability — a module-level function can be imported and called directly
#      in tests; a nested function cannot.
#   2. Decorator correctness — nesting would recreate a new decorated function
#      on every make_api_request() call, resetting tenacity's retry statistics
#      and state each time. At module level it is defined and decorated once.
# ---------------------------------------------------------------------------


def _is_html_response(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "")
    return "text/html" in content_type or response.text.lstrip().startswith("<!doctype")


@retry(
    # Only retry on our internal signal — not on every exception type.
    retry=retry_if_exception_type(_RetryableAPIError),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    # Jitter adds a small random offset to the exponential wait time — prevents
    # multiple pipelines failing simultaneously from retrying in lockstep and
    # hammering the API together (thundering herd problem).
    wait=wait_exponential_jitter(initial=_WAIT_MIN, max=_WAIT_MAX),
    # reraise=False means tenacity raises RetryError (not _RetryableAPIError) once
    # all attempts are exhausted. make_api_request() catches RetryError and converts
    # it to a clean APIRequestError. Do not change this to True.
    reraise=False,
)
def _execute_with_retry(
    method: str,
    url: str,
    auth: Optional[AuthBase],
    params: Optional[dict],
    json: Optional[dict],
    headers: Optional[dict],
    timeout: int,
) -> requests.Response:
    """
    Execute a single HTTP request attempt, decorated with tenacity retry logic.

    Signals tenacity to retry by raising _RetryableAPIError on network errors
    and retryable HTTP status codes. Raises APIRequestError immediately on
    non-retryable 4xx responses so retries are never wasted on caller errors.

    Not intended to be called directly — use make_api_request() instead.
    """
    attempt_number = _execute_with_retry.retry.statistics.get("attempt_number", 1)
    if attempt_number > 1:
        print(f"[api_request] Retry attempt {attempt_number}/{_MAX_ATTEMPTS} — {method} {url}")

    try:
        response = requests.request(
            method=method,
            url=url,
            auth=auth,
            params=params,
            json=json,
            headers=headers,
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        # Covers all network-level failures: timeouts, connection errors, DNS
        # failures, etc. All are transient and worth retrying.
        print(f"[api_request] Network error on {method} {url}: {e}")
        raise _RetryableAPIError(str(e)) from e

    if response.status_code in _RETRYABLE_STATUS_CODES:
        # 429: rate limited — back off and retry.
        # 5xx: server-side error — transient and worth retrying.
        print(
            f"[api_request] Retryable HTTP {response.status_code} on {method} {url} — will retry."
        )
        raise _RetryableAPIError(f"HTTP {response.status_code} from {url}")

    if not response.ok:
        # HTML response on any status code means a WAF/CDN block — treat as transient
        if _is_html_response(response):
            print(
                f"[api_request] HTML response on HTTP {response.status_code} "
                f"from {method} {url} — likely rate limited by CDN, retrying."
            )
            raise _RetryableAPIError(f"HTML response with HTTP {response.status_code} from {url}")

        # Non-retryable 4xx (e.g. 400, 401, 403, 404) — these are caller errors.
        # Retrying won't fix them, so raise immediately to avoid wasting attempts.
        raise APIRequestError(
            f"Non-retryable HTTP {response.status_code} on {method} {url}: {response.text[:300]}",
            status_code=response.status_code,
            response_text=response.text,
        )

    return response


# ---------------------------------------------------------------------------
# Public interface
#
# This is the only function the rest of the codebase should ever call directly.
# It owns two concerns that _execute_with_retry intentionally does not:
#   1. Input validation (HTTP method check) — fail fast before touching the network.
#   2. Error translation — converts tenacity's RetryError into a clean
#      APIRequestError so callers never need to know tenacity exists.
# ---------------------------------------------------------------------------


def make_api_request(
    method: str,
    url: str,
    auth: Optional[AuthBase] = None,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 600,
) -> requests.Response:
    """
    Make an HTTP API request with automatic retry on transient failures.

    Retries on:
        - Network / connection errors (requests.exceptions.RequestException)
        - HTTP status codes: 429 (rate limit), 500, 502, 503, 504

    Does NOT retry on:
        - 4xx errors (except 429) — these are caller errors and won't resolve on retry
        - Successful 2xx responses

    Args:
        method (str): HTTP method — "GET", "POST", or "PATCH".
        url (str): Full URL to send the request to.
        auth (AuthBase, optional): Auth object, e.g. HTTPBasicAuth. Defaults to None.
        params (dict, optional): URL query parameters. Defaults to None.
        json (dict, optional): JSON request body. Defaults to None.
        headers (dict, optional): Additional HTTP headers. Defaults to None.
        timeout (int, optional): Request timeout in seconds. Defaults to 600.

    Returns:
        requests.Response: The successful HTTP response object.

    Raises:
        ValueError: If an unsupported HTTP method is provided.
        APIRequestError: If the request fails after all retry attempts are
                         exhausted, or a non-retryable HTTP error is returned.
    """
    method = method.upper()
    if method not in {"GET", "POST", "PATCH"}:
        raise ValueError(f"Unsupported HTTP method: '{method}'. Must be one of: GET, POST, PATCH.")

    try:
        return _execute_with_retry(
            method=method,
            url=url,
            auth=auth,
            params=params,
            json=json,
            headers=headers,
            timeout=timeout,
        )
    except RetryError as e:
        # All attempts exhausted — unwrap tenacity's RetryError to surface the
        # actual underlying cause, then raise as a clean APIRequestError.
        cause = e.last_attempt.exception()
        raise APIRequestError(
            f"{method} {url} failed after {_MAX_ATTEMPTS} attempts. Last error: {cause}",
        ) from e
    except APIRequestError:
        # Non-retryable error raised directly inside _execute_with_retry —
        # pass through cleanly without wrapping it a second time.
        raise
