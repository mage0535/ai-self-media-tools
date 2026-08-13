from content_platform.bgm_catalog import select_unused_candidate, write_catalog_entry


def test_bgm_catalog_selects_fresh_metadata_without_storing_an_audio_path(tmp_path):
    catalog = tmp_path / "bgm_catalog.json"
    write_catalog_entry(
        catalog,
        {
            "source": "archive.org",
            "source_url": "https://archive.org/details/old-track",
            "license": "CC0",
            "fingerprint": "used-track",
            "mood": "calm piano",
            "audio_path": "/private/cache/old.mp3",
        },
    )

    result = select_unused_candidate(
        catalog,
        [
            {"source": "archive.org", "source_url": "https://archive.org/details/old-track", "license": "CC0", "fingerprint": "used-track", "mood": "calm piano"},
            {"source": "archive.org", "source_url": "https://archive.org/details/fresh-track", "license": "CC0", "fingerprint": "fresh-track", "mood": "warm piano"},
        ],
    )

    assert result["selected"]["fingerprint"] == "fresh-track"
    assert "audio_path" not in catalog.read_text(encoding="utf-8")
