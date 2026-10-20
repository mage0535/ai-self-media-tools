from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from content_platform.shotcraft_receipt import build_shotcraft_execution_receipt, validate_shotcraft_execution_receipt


def _media(path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "testsrc=size=96x64:rate=8", "-t", "1", "-pix_fmt", "yuv420p", str(path)
    ], check=True)


def _fixture(root: Path) -> dict:
    _media(root / "final.mp4")
    (root / "shots").mkdir()
    for name in ("shot_01A", "shot_01B"):
        shutil.copy2(root / "final.mp4", root / "shots" / f"{name}.mp4")
    return {"segments": [{
        "index": 1, "move_id": "zoom", "profile": "element_zoom_1", "rendered": True,
        "renderer": "film_renderer", "fallback": False, "shot_outputs": [
            {"name": "shot_01A", "path": "shots/shot_01A.mp4", "renderer": "playwright-frame-video", "fallback": False},
            {"name": "shot_01B", "path": "shots/shot_01B.mp4", "renderer": "playwright-frame-video", "fallback": False},
        ]
    }]}


def test_real_receipt_recomputes_media(tmp_path: Path):
    evidence = _fixture(tmp_path)
    receipt = build_shotcraft_execution_receipt(tmp_path, evidence)
    assert receipt["passed"] is True
    assert validate_shotcraft_execution_receipt(tmp_path, receipt)["passed"] is True


def test_tampered_shot_fails(tmp_path: Path):
    receipt = build_shotcraft_execution_receipt(tmp_path, _fixture(tmp_path))
    (tmp_path / "shots" / "shot_01A.mp4").write_bytes(b"not media")
    result = validate_shotcraft_execution_receipt(tmp_path, receipt)
    assert result["passed"] is False
    assert any("shot_invalid" in item or "shot_sha_mismatch" in item for item in result["failures"])


def test_duplicate_shot_name_fails(tmp_path: Path):
    evidence = _fixture(tmp_path)
    evidence["segments"][0]["shot_outputs"][1]["name"] = "shot_01A"
    receipt = build_shotcraft_execution_receipt(tmp_path, evidence)
    assert receipt["passed"] is False
    assert "duplicate_shot_name:shot_01A" in receipt["failures"]
