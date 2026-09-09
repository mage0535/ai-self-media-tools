import json
from pathlib import Path
from unittest.mock import patch

from content_platform.image_provider import ImageProviderError


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


def test_pexels_key_uses_unified_private_secret_loader():
    from scripts.pexels_auto_bg import _pexels_key

    with patch("content_platform.image_provider.load_secret", return_value="shared-key") as loader:
        assert _pexels_key() == "shared-key"

    loader.assert_called_once_with("PEXELS_API_KEY")


def test_semantic_queries_are_scene_specific_not_generic_single_words():
    from scripts.pexels_auto_bg import _semantic_queries

    script = """手机里装的AI工具越来越多，每个工具都带来一套新操作。

资料散得到处都是，注意力被切得稀碎。

第一步做减法，重复工具只留一个。

第二步明确分工，写稿、查资料、做图各用一个入口。

第三步固定工作流，把每一步写下来。

最近先别装新工具，把手头这套反复用熟。

只用一个主力入口完成今天的任务。

复盘实际产出，再决定保留哪个工具。"""
    queries = _semantic_queries(script, 8)

    assert len(queries) == 8
    assert len(set(queries)) == 8
    assert all(len(query.split()) >= 3 for query in queries)
    assert not {"technology", "computer", "productivity", "workspace"}.intersection(queries)
    assert any("multiple" in query or "overwhelmed" in query for query in queries)


def test_ai_fallback_continues_after_one_provider_failure(tmp_path: Path):
    from scripts.pexels_auto_bg import auto_fetch_backgrounds

    backgrounds = tmp_path / "backgrounds"
    backgrounds.mkdir()
    for index in range(1, 8):
        (backgrounds / f"bg_{index:02d}.jpg").write_bytes(f"existing-{index}".encode())

    def generated(_prompt, output, **_kwargs):
        Path(output).write_bytes(b"x" * 6000)
        return {"provider": "cloudflare", "model": "test"}

    attempts = {"count": 0, "prompts": [], "intents": []}

    def generate_after_retry(prompt, output, **kwargs):
        attempts["count"] += 1
        attempts["prompts"].append(prompt)
        attempts["intents"].append(kwargs.get("intent"))
        if attempts["count"] == 1:
            raise ImageProviderError("transient")
        return generated(prompt, output, **kwargs)

    with (
        patch("scripts.pexels_auto_bg._pexels_key", return_value=""),
        patch("content_platform.image_provider.generate_image", side_effect=generate_after_retry),
    ):
        rows = auto_fetch_backgrounds("AI workflow", "Title", tmp_path, "kuaishou")

    assert len(rows) == 1
    assert Path(rows[0]["background_image"]).is_file()
    assert attempts["prompts"][0] != attempts["prompts"][1]
    assert attempts["intents"] == ["fast_fallback", "fast_fallback"]
    report = json.loads((tmp_path / "asset_selection_attempts.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in report["attempts"]] == ["failed", "accepted"]
