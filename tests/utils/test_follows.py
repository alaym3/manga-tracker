from manga_tracker.utils.loaders.mangadex.follows import _extract_title


def test_extract_title_prefers_english():
    record = {"attributes": {"title": {"en": "Berserk", "ja": "ベルセルク", "ja-ro": "Berserk"}}}
    assert _extract_title(record) == "Berserk"


def test_extract_title_falls_back_to_romanized_japanese():
    record = {"attributes": {"title": {"ja-ro": "Berserk", "ja": "ベルセルク"}}}
    assert _extract_title(record) == "Berserk"


def test_extract_title_falls_back_to_first_available():
    record = {"attributes": {"title": {"ja": "ベルセルク"}}}
    assert _extract_title(record) == "ベルセルク"


def test_extract_title_empty_title_dict():
    record = {"attributes": {"title": {}}}
    assert _extract_title(record) == "Unknown"


def test_extract_title_missing_attributes():
    record = {}
    assert _extract_title(record) == "Unknown"
