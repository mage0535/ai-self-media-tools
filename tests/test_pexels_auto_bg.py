import json
from pathlib import Path
from unittest.mock import patch


class _Response:
    def __init__(self, payload: bytes): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.payload


def test_pexels_candidate_pool_skips_excluded_photo_id():
    from scripts.pexels_auto_bg import _download_pexels

    api = json.dumps({"photos": [
        {"id": 1, "url": "https://pexels.test/1", "photographer": "A", "photographer_url": "https://pexels.test/a", "src": {"large2x": "https://cdn.test/1.jpg"}},
        {"id": 2, "url": "https://pexels.test/2", "photographer": "B", "photographer_url": "https://pexels.test/b", "src": {"large2x": "https://cdn.test/2.jpg"}},
    ]}).encode()

    with patch("scripts.pexels_auto_bg.urllib.request.urlopen", side_effect=[_Response(api), _Response(b"photo-two")]):
        result = _download_pexels("technology", "key", exclude_ids={"1"})

    assert result["asset_id"] == "2"
    assert result["content"] == b"photo-two"


def test_pexels_candidate_pool_skips_historical_content_hash():
    from scripts.pexels_auto_bg import _download_pexels
    import hashlib

    duplicate = b"duplicate"
    fresh = b"fresh"
    api = json.dumps({"photos": [
        {"id": 1, "url": "https://pexels.test/1", "photographer": "A", "photographer_url": "", "src": {"large2x": "https://cdn.test/1.jpg"}},
        {"id": 2, "url": "https://pexels.test/2", "photographer": "B", "photographer_url": "", "src": {"large2x": "https://cdn.test/2.jpg"}},
    ]}).encode()
    with patch("scripts.pexels_auto_bg.urllib.request.urlopen", side_effect=[_Response(api), _Response(duplicate), _Response(fresh)]):
        result = _download_pexels("technology", "key", exclude_hashes={hashlib.sha256(duplicate).hexdigest()})

    assert result["asset_id"] == "2"
    assert result["content"] == fresh


def test_auto_fetch_counts_existing_files_and_adds_only_missing_unique_assets(tmp_path: Path):
    from scripts.pexels_auto_bg import auto_fetch_backgrounds

    backgrounds = tmp_path / "backgrounds"
    backgrounds.mkdir()
    for index in range(1, 7):
        (backgrounds / f"bg_{index:02d}.jpg").write_bytes(f"existing-{index}".encode())
    photos = iter([
        {"content": b"new-a", "source_url": "https://pexels.test/a", "artist": "A", "artist_url": "", "asset_id": "a"},
        {"content": b"new-b", "source_url": "https://pexels.test/b", "artist": "B", "artist_url": "", "asset_id": "b"},
    ])
    with patch("scripts.pexels_auto_bg._pexels_key", return_value="key"), patch("scripts.pexels_auto_bg._download_pexels", side_effect=lambda *args, **kwargs: next(photos)):
        result = auto_fetch_backgrounds("AI workflow", "Title", tmp_path, "kuaishou")

    assert len(result) == 2
    assert {row["asset_id"] for row in result} == {"a", "b"}
    assert (backgrounds / "bg_07.jpg").is_file()
    assert (backgrounds / "bg_08.jpg").is_file()


def test_force_fetch_excludes_historical_hashes(tmp_path: Path):
    from scripts.pexels_auto_bg import auto_fetch_backgrounds
    import hashlib

    old = b"historical"
    fresh = [f"fresh-{index}".encode() for index in range(8)]
    payloads = iter([
        {"content": old, "source_url": "https://pexels.test/old", "artist": "Old", "artist_url": "", "asset_id": "old"},
        *[
            {"content": content, "source_url": f"https://pexels.test/{index}", "artist": "A", "artist_url": "", "asset_id": str(index)}
            for index, content in enumerate(fresh)
        ],
    ])
    with patch("scripts.pexels_auto_bg._pexels_key", return_value="key"), patch("scripts.pexels_auto_bg._semantic_queries", return_value=[f"q{i}" for i in range(9)]), patch("scripts.pexels_auto_bg._download_pexels", side_effect=lambda *args, **kwargs: next(payloads)):
        rows = auto_fetch_backgrounds("AI", "Title", tmp_path, "kuaishou", force=True, excluded_hashes={hashlib.sha256(old).hexdigest()})

    assert len(rows) == 8
    assert all(hashlib.sha256(Path(row["background_image"]).read_bytes()).hexdigest() != hashlib.sha256(old).hexdigest() for row in rows)
