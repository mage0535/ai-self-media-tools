import hashlib
import json
from pathlib import Path
from unittest.mock import patch


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_auto_fetch_returns_and_persists_complete_pexels_provenance(tmp_path: Path):
    from scripts.pexels_auto_bg import auto_fetch_backgrounds

    image_bytes = b"unique-pexels-image"
    photo = {
        "id": 123,
        "url": "https://www.pexels.com/photo/example-123/",
        "photographer": "Example Photographer",
        "width": 1080,
        "height": 1920,
        "src": {"large2x": "https://images.pexels.com/photos/123/example.jpeg"},
    }
    api_payload = json.dumps({"photos": [photo]}).encode()

    with patch("scripts.pexels_auto_bg._pexels_key", return_value="test-key"), patch(
        "scripts.pexels_auto_bg._semantic_queries", return_value=["workflow"]
    ), patch(
        "scripts.pexels_auto_bg.urllib.request.urlopen",
        side_effect=[_Response(api_payload), _Response(image_bytes)],
    ), patch("scripts.pexels_auto_bg.time.sleep"):
        assets = auto_fetch_backgrounds("workflow", "audit", tmp_path, "douyin_ai")

    assert len(assets) == 1
    asset = assets[0]
    assert asset["photo_id"] == "123"
    assert asset["page_url"] == photo["url"]
    assert asset["download_url"] == photo["src"]["large2x"]
    assert asset["photographer"] == photo["photographer"]
    assert asset["license"] == "Pexels License"
    assert asset["license_url"] == "https://www.pexels.com/license/"
    assert asset["query"] == "workflow"
    assert asset["downloaded_at"].endswith("+00:00")
    assert asset["sha256"] == hashlib.sha256(image_bytes).hexdigest()
    assert asset["dimensions"] == {"width": 1080, "height": 1920}
    assert asset["semantic_match_score"] > 0
    assert asset["match_reason"]
    assert asset["semantic_tags"] == ["workflow", "pexels", "real_scene"]
    assert Path(asset["path"]).read_bytes() == image_bytes
    assert asset["background_image"] == asset["path"]
    saved = json.loads((tmp_path / "visual_assets_auto.json").read_text(encoding="utf-8"))
    assert saved["assignments"][0] == asset


def test_auto_fetch_reuses_only_manifest_backed_provenance(tmp_path: Path):
    from scripts.pexels_auto_bg import auto_fetch_backgrounds, write_auto_assets

    assignments = []
    for scene in range(1, 9):
        path = tmp_path / "backgrounds" / f"bg_{scene:02d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"image-{scene}".encode())
        assignments.append(
            {
                "scene": scene,
                "path": str(path),
                "background_image": str(path),
                "photo_id": str(scene),
                "page_url": f"https://www.pexels.com/photo/{scene}/",
                "download_url": f"https://images.pexels.com/{scene}.jpg",
                "photographer": "Example",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "query": "workflow",
                "downloaded_at": "2026-09-16T00:00:00+00:00",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dimensions": {"width": 1080, "height": 1920},
            }
        )
    write_auto_assets(assignments, tmp_path, "douyin_ai")

    with patch("scripts.pexels_auto_bg._pexels_key") as key:
        reused = auto_fetch_backgrounds("workflow", "audit", tmp_path, "douyin_ai")

    key.assert_not_called()
    assert reused == assignments


def test_runner_provenance_consumes_background_image_and_preserves_audit_fields(tmp_path: Path):
    from scripts.video_toolchain_runner import _asset_provenance_records

    image = tmp_path / "bg.jpg"
    image.write_bytes(b"image")
    record = _asset_provenance_records(
        [
            {
                "scene": 1,
                "background_image": str(image),
                "photo_id": "123",
                "page_url": "https://www.pexels.com/photo/example-123/",
                "download_url": "https://images.pexels.com/photos/123/example.jpeg",
                "photographer": "Example Photographer",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "query": "workflow",
                "downloaded_at": "2026-09-16T00:00:00+00:00",
                "sha256": "abc",
                "dimensions": {"width": 1080, "height": 1920},
            }
        ]
    )[0]

    assert record["path"] == str(image)
    assert record["source_url"] == "https://www.pexels.com/photo/example-123/"
    for field in (
        "photo_id",
        "page_url",
        "download_url",
        "photographer",
        "license",
        "license_url",
        "query",
        "downloaded_at",
        "sha256",
        "dimensions",
    ):
        assert record[field]


def test_materialization_preserves_pexels_provenance(tmp_path: Path):
    from scripts.video_toolchain_runner import _materialize_visual_backgrounds

    source = tmp_path / "source.jpg"
    source.write_bytes(b"pexels")
    expected = {
        "scene": 1,
        "background_image": str(source),
        "photo_id": "123",
        "page_url": "https://www.pexels.com/photo/example-123/",
        "download_url": "https://images.pexels.com/photos/123/example.jpeg",
        "photographer": "Example Photographer",
        "license": "Pexels License",
        "license_url": "https://www.pexels.com/license/",
        "query": "workflow",
        "downloaded_at": "2026-09-16T00:00:00+00:00",
        "sha256": "abc",
        "dimensions": {"width": 1080, "height": 1920},
    }

    materialized = _materialize_visual_backgrounds(
        tmp_path / "out", {"assignments": [expected]}
    )[0]

    for field in (
        "photo_id",
        "page_url",
        "download_url",
        "photographer",
        "license_url",
        "query",
        "downloaded_at",
        "sha256",
        "dimensions",
    ):
        assert materialized[field] == expected[field]
    assert materialized["source_url"] == expected["page_url"]


def _valid_provenance_records(tmp_path: Path, count: int = 8) -> list[dict]:
    records = []
    for scene in range(1, count + 1):
        path = tmp_path / f"bg-{scene}.jpg"
        path.write_bytes(f"image-{scene}".encode())
        records.append(
            {
                "scene_id": str(scene),
                "path": str(path),
                "source_url": f"https://www.pexels.com/photo/{scene}/",
                "photo_id": str(scene),
                "page_url": f"https://www.pexels.com/photo/{scene}/",
                "download_url": f"https://images.pexels.com/{scene}.jpg",
                "photographer": "Example",
                "license": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "query": "workflow",
                "downloaded_at": "2026-09-16T00:00:00+00:00",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dimensions": {"width": 1080, "height": 1920},
            }
        )
    return records


def test_background_provenance_gate_rejects_empty_assets():
    from scripts.video_toolchain_runner import _background_provenance_gate

    gate = _background_provenance_gate([], required_scenes=8)

    assert gate["passed"] is False
    assert "background_assets_empty" in gate["failures"]


def test_background_provenance_gate_rejects_missing_license(tmp_path: Path):
    from scripts.video_toolchain_runner import _background_provenance_gate

    records = _valid_provenance_records(tmp_path)
    records[3]["license"] = ""
    gate = _background_provenance_gate(records, required_scenes=8)

    assert gate["passed"] is False
    assert "scene_4:asset_license_missing" in gate["failures"]


def test_background_provenance_gate_rejects_incomplete_pexels_evidence(tmp_path: Path):
    from scripts.video_toolchain_runner import _background_provenance_gate

    records = _valid_provenance_records(tmp_path)
    records[0].update(
        {
            "photo_id": "",
            "page_url": records[0]["source_url"],
            "download_url": "https://images.pexels.com/1.jpg",
            "photographer": "Example",
            "license_url": "https://www.pexels.com/license/",
            "query": "workflow",
            "downloaded_at": "2026-09-16T00:00:00+00:00",
            "sha256": hashlib.sha256(Path(records[0]["path"]).read_bytes()).hexdigest(),
            "dimensions": {"width": 1080, "height": 1920},
        }
    )

    gate = _background_provenance_gate(records, required_scenes=8)

    assert gate["passed"] is False
    assert "scene_1:pexels_provenance_missing:photo_id" in gate["failures"]


def test_background_provenance_gate_rejects_insufficient_scene_coverage(tmp_path: Path):
    from scripts.video_toolchain_runner import _background_provenance_gate

    gate = _background_provenance_gate(
        _valid_provenance_records(tmp_path, count=7), required_scenes=8
    )

    assert gate["passed"] is False
    assert "background_scene_coverage_insufficient:7/8" in gate["failures"]
