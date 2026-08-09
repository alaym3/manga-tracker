"""Shared fakes for MangaDex loader / api_request tests."""

from typing import List, Optional
from urllib.parse import parse_qs, urlparse


class FakeResponse:
    """Minimal stand-in for requests.Response used by tests."""

    def __init__(
        self,
        json_body: Optional[dict] = None,
        status_code: int = 200,
        ok: bool = True,
        headers: Optional[dict] = None,
        text: str = "",
    ):
        self._json_body = json_body if json_body is not None else {}
        self.status_code = status_code
        self.ok = ok
        self.headers = headers or {}
        self.text = text

    def json(self) -> dict:
        return self._json_body


class RecordedCall:
    """A single call captured by FakeRequestSequence, with the query string parsed."""

    def __init__(self, method: str, url: str, headers: Optional[dict], timeout: Optional[int]):
        self.method = method
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.query = parse_qs(urlparse(url).query, keep_blank_values=True)


class FakeRequestSequence:
    """
    Callable matching make_api_request's call shape. Pops canned FakeResponse
    objects off a queue in order and records every call for inspection —
    the seam that makes the stateful pagination loop testable without
    monkeypatching a module-level import.
    """

    def __init__(self, responses: List[FakeResponse]):
        self._responses = list(responses)
        self.calls: List[RecordedCall] = []

    def __call__(
        self,
        method: str,
        url: str,
        timeout: Optional[int] = None,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> FakeResponse:
        self.calls.append(RecordedCall(method=method, url=url, headers=headers, timeout=timeout))
        if not self._responses:
            raise AssertionError("FakeRequestSequence exhausted — not enough canned responses.")
        return self._responses.pop(0)


def make_page(records: List[dict], total: Optional[int] = None) -> dict:
    body = {"data": records}
    if total is not None:
        body["total"] = total
    return body


def make_record(record_id: str, created_at: str, manga_id: Optional[str] = None) -> dict:
    record = {"id": record_id, "attributes": {"createdAt": created_at}}
    if manga_id is not None:
        record["relationships"] = [{"type": "manga", "id": manga_id}]
    return record
