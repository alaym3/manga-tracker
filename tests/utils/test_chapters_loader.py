from datetime import datetime, timezone

from manga_tracker.utils.loaders.mangadex import chapters
from tests.utils.conftest import FakeRequestSequence, FakeResponse, make_page, make_record

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# _extract_manga_id
# ---------------------------------------------------------------------------


def test_extract_manga_id_finds_manga_relationship():
    payload = {
        "relationships": [
            {"type": "scanlation_group", "id": "group-1"},
            {"type": "manga", "id": "manga-1"},
        ]
    }
    assert chapters._extract_manga_id(payload) == "manga-1"


def test_extract_manga_id_no_manga_relationship():
    payload = {"relationships": [{"type": "scanlation_group", "id": "group-1"}]}
    assert chapters._extract_manga_id(payload) is None


def test_extract_manga_id_no_relationships_key():
    assert chapters._extract_manga_id({}) is None


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_config_uses_translated_language_and_default_includes():
    assert chapters._CONFIG.chunk_days == 7
    assert chapters._CONFIG.extra_query_params == (("translatedLanguage[]", "en"),)
    assert chapters._CONFIG.default_includes == ["scanlation_group"]


def test_stream_raw_chapters_by_chunk_sends_expected_query_params():
    fake = FakeRequestSequence(
        [FakeResponse(make_page([make_record("c1", "2024-01-01T05:00:00+00:00", manga_id="m1")]))]
    )

    results = list(
        chapters.stream_raw_chapters_by_chunk(
            pipeline_uuid="test",
            since=datetime(2024, 1, 1, tzinfo=_UTC),
            max_records=1,
            make_request=fake,
        )
    )

    assert len(results) == 1
    _, records = results[0]
    assert [r["id"] for r in records] == ["c1"]

    query = fake.calls[0].query
    assert query["translatedLanguage[]"] == ["en"]
    assert query["includes[]"] == ["scanlation_group"]
