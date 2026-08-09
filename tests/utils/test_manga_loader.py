from datetime import datetime, timezone

from manga_tracker.utils.loaders.mangadex import chunked_pagination as cp
from manga_tracker.utils.loaders.mangadex import manga
from tests.utils.conftest import FakeRequestSequence, FakeResponse, make_page, make_record

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_config_has_no_translated_language_param():
    assert manga._CONFIG.extra_query_params == ()
    assert manga._CONFIG.chunk_days == 60
    assert manga._CONFIG.default_includes == ["author", "artist", "cover_art", "tags"]


def test_stream_raw_manga_by_chunk_sends_expected_query_params():
    fake = FakeRequestSequence(
        [FakeResponse(make_page([make_record("m1", "2024-01-01T05:00:00+00:00")]))]
    )

    results = list(
        manga.stream_raw_manga_by_chunk(
            pipeline_uuid="test",
            since=datetime(2024, 1, 1, tzinfo=_UTC),
            max_records=1,
            make_request=fake,
        )
    )

    assert len(results) == 1
    _, records = results[0]
    assert [r["id"] for r in records] == ["m1"]

    query = fake.calls[0].query
    assert "translatedLanguage[]" not in query  # intentional, non-bug divergence from chapters.py
    assert query["includes[]"] == ["author", "artist", "cover_art", "tags"]


# ---------------------------------------------------------------------------
# Regression: unencoded-bracket query strings (manga.py previously used plain
# quote(), which percent-encoded brackets despite the module's own docstring
# claiming MangaDex compatibility required literal brackets).
# ---------------------------------------------------------------------------


def test_bracket_params_are_unencoded_in_outgoing_request():
    fake = FakeRequestSequence(
        [FakeResponse(make_page([make_record("m1", "2024-01-01T05:00:00+00:00")]))]
    )

    gen = manga.stream_raw_manga_by_chunk(
        pipeline_uuid="test",
        since=datetime(2024, 1, 1, tzinfo=_UTC),
        max_records=1,
        make_request=fake,
    )
    next(gen)  # one chunk is enough to inspect the outgoing request

    assert "order[createdAt]=asc" in fake.calls[0].url
    assert "order%5BcreatedAt%5D" not in fake.calls[0].url


# ---------------------------------------------------------------------------
# Regression: manga.py previously had no ChunkTooLargeError / offset-limit
# guard at all, so a chunk crossing the 10k-offset ceiling would crash the
# whole load instead of splitting like chapters.py already does.
# ---------------------------------------------------------------------------


def test_offset_guard_splits_instead_of_crashing(monkeypatch):
    start = datetime(2024, 1, 1, 0, 0, tzinfo=_UTC)
    end = datetime(2024, 1, 1, 2, 0, tzinfo=_UTC)
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
        manga.stream_raw_manga_by_chunk(
            pipeline_uuid="test",
            since=start,
            limit=2,
            make_request=fake,
        )
    )

    all_ids = [r["id"] for _, records in results for r in records]
    assert all_ids == ["sub1", "sub2"]
