from datetime import datetime, timezone

import pytest

from manga_tracker.utils.loaders.mangadex.chapters import (
    ChunkTooLargeError,
    _generate_date_chunks,
    _parse_created_at,
    _split_chunk_range,
)

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# _generate_date_chunks
# ---------------------------------------------------------------------------


def test_generate_date_chunks_covers_full_range():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 1, 15, tzinfo=_UTC)
    chunks = list(_generate_date_chunks(start, end, chunk_days=7))
    assert len(chunks) == 2
    assert chunks[0] == (start, datetime(2024, 1, 8, tzinfo=_UTC))
    assert chunks[1] == (datetime(2024, 1, 8, tzinfo=_UTC), end)


def test_generate_date_chunks_range_shorter_than_chunk():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 1, 3, tzinfo=_UTC)
    chunks = list(_generate_date_chunks(start, end, chunk_days=7))
    assert len(chunks) == 1
    assert chunks[0] == (start, end)


def test_generate_date_chunks_empty_range():
    dt = datetime(2024, 1, 1, tzinfo=_UTC)
    chunks = list(_generate_date_chunks(dt, dt, chunk_days=7))
    assert chunks == []


def test_generate_date_chunks_contiguous_no_gaps():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 2, 1, tzinfo=_UTC)
    chunks = list(_generate_date_chunks(start, end, chunk_days=7))
    # Each chunk's end is the next chunk's start
    for i in range(len(chunks) - 1):
        assert chunks[i][1] == chunks[i + 1][0]
    assert chunks[0][0] == start
    assert chunks[-1][1] == end


# ---------------------------------------------------------------------------
# _split_chunk_range
# ---------------------------------------------------------------------------


def test_split_chunk_range_produces_two_contiguous_halves():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 1, 15, tzinfo=_UTC)
    halves = _split_chunk_range(start, end)
    assert len(halves) == 2
    assert halves[0][0] == start
    assert halves[0][1] == halves[1][0]
    assert halves[1][1] == end


def test_split_chunk_range_too_small_raises():
    start = datetime(2024, 1, 1, 0, 0, tzinfo=_UTC)
    end = datetime(2024, 1, 1, 0, 30, tzinfo=_UTC)  # 30 min — below 1 hour minimum
    with pytest.raises(ChunkTooLargeError):
        _split_chunk_range(start, end)


# ---------------------------------------------------------------------------
# _parse_created_at
# ---------------------------------------------------------------------------


def test_parse_created_at_valid_timestamp():
    record = {"attributes": {"createdAt": "2024-01-15T10:30:00+00:00"}}
    result = _parse_created_at(record)
    assert result is not None
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 10


def test_parse_created_at_missing_key():
    record = {"attributes": {}}
    assert _parse_created_at(record) is None


def test_parse_created_at_no_attributes():
    record = {}
    assert _parse_created_at(record) is None
