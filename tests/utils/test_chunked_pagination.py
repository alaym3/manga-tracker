from datetime import datetime, timezone

import pytest

from manga_tracker.utils.loaders.mangadex import chunked_pagination as cp
from tests.utils.conftest import FakeRequestSequence, FakeResponse, make_page, make_record

_UTC = timezone.utc


def _config(**overrides) -> cp.ChunkedResourceConfig:
    defaults = dict(
        resource_name="thing",
        url="https://api.example.com/thing",
        default_includes=["cover_art"],
        headers={"Accept": "application/json"},
        extra_query_params=(),
        chunk_days=7,
        min_chunk_hours=1,
        page_limit=2,
        request_timeout_seconds=30,
        sleep_between_pages=0,
    )
    defaults.update(overrides)
    return cp.ChunkedResourceConfig(**defaults)


# ---------------------------------------------------------------------------
# _generate_date_chunks
# ---------------------------------------------------------------------------


def test_generate_date_chunks_covers_full_range():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 1, 15, tzinfo=_UTC)
    chunks = list(cp._generate_date_chunks(start, end, chunk_days=7))
    assert len(chunks) == 2
    assert chunks[0] == (start, datetime(2024, 1, 8, tzinfo=_UTC))
    assert chunks[1] == (datetime(2024, 1, 8, tzinfo=_UTC), end)


def test_generate_date_chunks_range_shorter_than_chunk():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 1, 3, tzinfo=_UTC)
    chunks = list(cp._generate_date_chunks(start, end, chunk_days=7))
    assert len(chunks) == 1
    assert chunks[0] == (start, end)


def test_generate_date_chunks_empty_range():
    dt = datetime(2024, 1, 1, tzinfo=_UTC)
    chunks = list(cp._generate_date_chunks(dt, dt, chunk_days=7))
    assert chunks == []


def test_generate_date_chunks_contiguous_no_gaps():
    start = datetime(2024, 1, 1, tzinfo=_UTC)
    end = datetime(2024, 2, 1, tzinfo=_UTC)
    chunks = list(cp._generate_date_chunks(start, end, chunk_days=7))
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
    halves = cp._split_chunk_range(start, end)
    assert len(halves) == 2
    assert halves[0][0] == start
    assert halves[0][1] == halves[1][0]
    assert halves[1][1] == end


def test_split_chunk_range_too_small_raises():
    start = datetime(2024, 1, 1, 0, 0, tzinfo=_UTC)
    end = datetime(2024, 1, 1, 0, 30, tzinfo=_UTC)  # 30 min — below 1 hour minimum
    with pytest.raises(cp.ChunkTooLargeError):
        cp._split_chunk_range(start, end)


# ---------------------------------------------------------------------------
# _parse_created_at
# ---------------------------------------------------------------------------


def test_parse_created_at_valid_timestamp():
    record = {"attributes": {"createdAt": "2024-01-15T10:30:00+00:00"}}
    result = cp._parse_created_at(record)
    assert result is not None
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 10


def test_parse_created_at_missing_key():
    record = {"attributes": {}}
    assert cp._parse_created_at(record) is None


def test_parse_created_at_no_attributes():
    record = {}
    assert cp._parse_created_at(record) is None


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


def test_build_params_preserves_unencoded_brackets():
    params = cp._build_params(
        offset=0,
        limit=100,
        includes=[],
        since=datetime(2024, 1, 1, tzinfo=_UTC),
    )
    assert "order[createdAt]=asc" in params
    assert "order%5BcreatedAt%5D" not in params


def test_build_params_appends_extra_query_params():
    params = cp._build_params(
        offset=0,
        limit=100,
        includes=[],
        since=datetime(2024, 1, 1, tzinfo=_UTC),
        extra_query_params=(("translatedLanguage[]", "en"),),
    )
    assert "translatedLanguage[]=en" in params


def test_build_params_repeats_includes():
    params = cp._build_params(
        offset=0,
        limit=100,
        includes=["author", "artist"],
        since=datetime(2024, 1, 1, tzinfo=_UTC),
    )
    assert params.count("includes[]=") == 2
    assert "includes[]=author" in params
    assert "includes[]=artist" in params


# ---------------------------------------------------------------------------
# _collect_chunk_records
# ---------------------------------------------------------------------------


def test_collect_chunk_records_advances_offset_across_pages():
    chunk_start = datetime(2024, 1, 1, tzinfo=_UTC)
    chunk_end = datetime(2024, 1, 2, tzinfo=_UTC)
    fake = FakeRequestSequence(
        [
            FakeResponse(
                make_page(
                    [
                        make_record("r1", "2024-01-01T01:00:00+00:00"),
                        make_record("r2", "2024-01-01T02:00:00+00:00"),
                    ]
                )
            ),
            FakeResponse(make_page([make_record("r3", "2024-01-01T03:00:00+00:00")])),
        ]
    )

    records = cp._collect_chunk_records(
        config=_config(page_limit=2),
        pipeline_uuid="test",
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        limit=2,
        includes=[],
        max_records_remaining=None,
        make_request=fake,
    )

    assert [r["id"] for r in records] == ["r1", "r2", "r3"]
    assert len(fake.calls) == 2
    assert fake.calls[0].query["offset"] == ["0"]
    assert fake.calls[1].query["offset"] == ["2"]


def test_collect_chunk_records_stops_at_chunk_boundary():
    chunk_start = datetime(2024, 1, 1, tzinfo=_UTC)
    chunk_end = datetime(2024, 1, 2, tzinfo=_UTC)
    fake = FakeRequestSequence(
        [
            FakeResponse(
                make_page(
                    [
                        make_record("in_range", "2024-01-01T01:00:00+00:00"),
                        make_record("out_of_range", "2024-01-02T01:00:00+00:00"),
                    ]
                )
            ),
        ]
    )

    records = cp._collect_chunk_records(
        config=_config(),
        pipeline_uuid="test",
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        limit=2,
        includes=[],
        max_records_remaining=None,
        make_request=fake,
    )

    assert [r["id"] for r in records] == ["in_range"]
    assert len(fake.calls) == 1  # boundary hit within the page — no second page fetched


def test_collect_chunk_records_respects_max_records_remaining():
    chunk_start = datetime(2024, 1, 1, tzinfo=_UTC)
    chunk_end = datetime(2024, 1, 2, tzinfo=_UTC)
    fake = FakeRequestSequence(
        [
            FakeResponse(
                make_page(
                    [
                        make_record("r1", "2024-01-01T01:00:00+00:00"),
                        make_record("r2", "2024-01-01T02:00:00+00:00"),
                    ]
                )
            ),
        ]
    )

    records = cp._collect_chunk_records(
        config=_config(),
        pipeline_uuid="test",
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        limit=2,
        includes=[],
        max_records_remaining=1,
        make_request=fake,
    )

    assert [r["id"] for r in records] == ["r1"]


def test_collect_chunk_records_raises_at_offset_limit(monkeypatch):
    monkeypatch.setattr(cp, "_OFFSET_LIMIT", 4)
    chunk_start = datetime(2024, 1, 1, tzinfo=_UTC)
    chunk_end = datetime(2024, 1, 2, tzinfo=_UTC)
    full_page = FakeResponse(
        make_page(
            [
                make_record("a", "2024-01-01T01:00:00+00:00"),
                make_record("b", "2024-01-01T01:00:00+00:00"),
            ]
        )
    )
    fake = FakeRequestSequence([full_page, full_page])

    with pytest.raises(cp.ChunkTooLargeError):
        cp._collect_chunk_records(
            config=_config(page_limit=2),
            pipeline_uuid="test",
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            limit=2,
            includes=[],
            max_records_remaining=None,
            make_request=fake,
        )


# ---------------------------------------------------------------------------
# stream_records_by_chunk
# ---------------------------------------------------------------------------


def test_stream_records_by_chunk_yields_per_chunk_including_empty(monkeypatch):
    chunk1 = (datetime(2024, 1, 1, tzinfo=_UTC), datetime(2024, 1, 2, tzinfo=_UTC))
    chunk2 = (datetime(2024, 1, 2, tzinfo=_UTC), datetime(2024, 1, 3, tzinfo=_UTC))
    monkeypatch.setattr(
        cp, "_generate_date_chunks", lambda since, before, chunk_days: iter([chunk1, chunk2])
    )

    fake = FakeRequestSequence(
        [
            FakeResponse(make_page([make_record("r1", "2024-01-01T05:00:00+00:00")])),
            FakeResponse(make_page([])),
        ]
    )

    results = list(
        cp.stream_records_by_chunk(
            config=_config(),
            pipeline_uuid="test",
            since=chunk1[0],
            make_request=fake,
        )
    )

    assert results == [
        (chunk1[1], [make_record("r1", "2024-01-01T05:00:00+00:00")]),
        (chunk2[1], []),
    ]


def test_stream_records_by_chunk_splits_and_requeues_on_chunk_too_large(monkeypatch):
    start = datetime(2024, 1, 1, 0, 0, tzinfo=_UTC)
    end = datetime(2024, 1, 1, 2, 0, tzinfo=_UTC)
    midpoint = datetime(2024, 1, 1, 1, 0, tzinfo=_UTC)
    monkeypatch.setattr(
        cp, "_generate_date_chunks", lambda since, before, chunk_days: iter([(start, end)])
    )
    monkeypatch.setattr(cp, "_OFFSET_LIMIT", 2)

    full_page = FakeResponse(
        make_page(
            [
                make_record("overflow_a", "2024-01-01T00:10:00+00:00"),
                make_record("overflow_b", "2024-01-01T00:20:00+00:00"),
            ]
        )
    )
    sub_chunk_1_page = FakeResponse(make_page([make_record("sub1", "2024-01-01T00:30:00+00:00")]))
    sub_chunk_2_page = FakeResponse(make_page([make_record("sub2", "2024-01-01T01:30:00+00:00")]))
    fake = FakeRequestSequence([full_page, sub_chunk_1_page, sub_chunk_2_page])

    results = list(
        cp.stream_records_by_chunk(
            config=_config(page_limit=2, min_chunk_hours=1),
            pipeline_uuid="test",
            since=start,
            make_request=fake,
        )
    )

    assert [chunk_end for chunk_end, _ in results] == [midpoint, end]
    assert [r["id"] for _, records in results for r in records] == ["sub1", "sub2"]


def test_stream_records_by_chunk_stops_at_max_records(monkeypatch):
    chunk1 = (datetime(2024, 1, 1, tzinfo=_UTC), datetime(2024, 1, 2, tzinfo=_UTC))
    chunk2 = (datetime(2024, 1, 2, tzinfo=_UTC), datetime(2024, 1, 3, tzinfo=_UTC))
    chunk3 = (datetime(2024, 1, 3, tzinfo=_UTC), datetime(2024, 1, 4, tzinfo=_UTC))
    monkeypatch.setattr(
        cp,
        "_generate_date_chunks",
        lambda since, before, chunk_days: iter([chunk1, chunk2, chunk3]),
    )

    fake = FakeRequestSequence(
        [
            FakeResponse(
                make_page(
                    [
                        make_record("r1", "2024-01-01T05:00:00+00:00"),
                        make_record("r2", "2024-01-01T06:00:00+00:00"),
                    ]
                )
            ),
            FakeResponse(
                make_page(
                    [
                        make_record("r3", "2024-01-02T05:00:00+00:00"),
                        make_record("r4", "2024-01-02T06:00:00+00:00"),
                    ]
                )
            ),
        ]
    )

    # page_limit=5 so each 2-record page is under the limit and ends its
    # chunk naturally after one request — isolates the max_records cutoff
    # (tested here) from the separate "fetch next page" pagination behavior.
    results = list(
        cp.stream_records_by_chunk(
            config=_config(page_limit=5),
            pipeline_uuid="test",
            since=chunk1[0],
            max_records=3,
            make_request=fake,
        )
    )

    total_records = sum(len(records) for _, records in results)
    assert total_records == 3
    assert len(fake.calls) == 2  # never fetched chunk3
