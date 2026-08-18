from __future__ import annotations

from pathlib import Path

from scripts import visual_asset_gate


def test_gate_rejects_missing_semantic_evidence(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "tiktok"
    video.mkdir()
    (video / "scene_manifest.json").write_text(
        '{"scenes":[{"scene_id":"s01","asset":{"source":"missing.mp4"}}]}',
        encoding="utf-8",
    )
    (video / "footage_provenance.json").write_text('[{}]', encoding="utf-8")
    result = visual_asset_gate.validate_assets(video, "tiktok")
    assert result["passed"] is False
    assert "scene_provenance_count_mismatch" in result["failures"]


def test_distance_detects_near_duplicate_visuals() -> None:
    assert visual_asset_gate._distance("0000000000000000", "0000000000000001") == 1
    assert visual_asset_gate._distance("0000000000000000", "ffffffffffffffff") == 64
