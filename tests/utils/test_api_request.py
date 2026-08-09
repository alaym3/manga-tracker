from unittest.mock import MagicMock

import pytest
import tenacity

from manga_tracker.utils.helpers import api_request as api_request_module
from manga_tracker.utils.helpers.api_request import APIRequestError, make_api_request


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """Tenacity's exponential-jitter wait would otherwise really sleep between retries."""
    monkeypatch.setattr(api_request_module._execute_with_retry.retry, "wait", tenacity.wait_none())


def _mock_response(status_code, ok, text="", headers=None, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.text = text
    response.headers = headers or {}
    response.json.return_value = json_body or {}
    return response


def test_success_no_retry(monkeypatch):
    response = _mock_response(200, ok=True, json_body={"data": []})
    request_mock = MagicMock(return_value=response)
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    result = make_api_request(method="GET", url="https://example.com")

    assert result is response
    assert request_mock.call_count == 1


def test_retryable_5xx_then_success(monkeypatch):
    fail_response = _mock_response(503, ok=False, text="unavailable")
    ok_response = _mock_response(200, ok=True, json_body={"data": []})
    request_mock = MagicMock(side_effect=[fail_response, ok_response])
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    result = make_api_request(method="GET", url="https://example.com")

    assert result is ok_response
    assert request_mock.call_count == 2


def test_retries_exhausted_raises_api_request_error(monkeypatch):
    fail_response = _mock_response(500, ok=False, text="server error")
    request_mock = MagicMock(return_value=fail_response)
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    with pytest.raises(APIRequestError):
        make_api_request(method="GET", url="https://example.com")

    assert request_mock.call_count == api_request_module._MAX_ATTEMPTS


def test_network_error_retried_then_wrapped(monkeypatch):
    import requests as requests_lib

    request_mock = MagicMock(side_effect=requests_lib.exceptions.ConnectionError("boom"))
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    with pytest.raises(APIRequestError):
        make_api_request(method="GET", url="https://example.com")

    assert request_mock.call_count == api_request_module._MAX_ATTEMPTS


def test_invalid_method_raises_value_error():
    with pytest.raises(ValueError):
        make_api_request(method="DELETE", url="https://example.com")


# ---------------------------------------------------------------------------
# Regression: a non-retryable, non-HTML 4xx used to retry _MAX_ATTEMPTS times
# despite the docstring promising it wouldn't — an unconditional raise fired
# before the (previously unreachable) non-retryable branch. This is the test
# that would have caught that bug.
# ---------------------------------------------------------------------------


def test_non_retryable_4xx_fails_fast_without_retrying(monkeypatch):
    response = _mock_response(
        404,
        ok=False,
        text="not found",
        headers={"Content-Type": "application/json"},
    )
    request_mock = MagicMock(return_value=response)
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    with pytest.raises(APIRequestError) as exc_info:
        make_api_request(method="GET", url="https://example.com")

    assert request_mock.call_count == 1
    assert exc_info.value.status_code == 404


def test_html_response_on_4xx_is_treated_as_retryable(monkeypatch):
    html_response = _mock_response(
        403,
        ok=False,
        text="<!doctype html><html>blocked</html>",
        headers={"Content-Type": "text/html"},
    )
    request_mock = MagicMock(return_value=html_response)
    monkeypatch.setattr(api_request_module.requests, "request", request_mock)

    with pytest.raises(APIRequestError):
        make_api_request(method="GET", url="https://example.com")

    # Still retried up to the normal attempt cap — the fix only changes
    # non-HTML 4xx handling, not the legitimate WAF/CDN-block retry path.
    assert request_mock.call_count == api_request_module._MAX_ATTEMPTS
