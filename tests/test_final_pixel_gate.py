from __future__ import annotations

import subprocess
from pathlib import Path

from content_platform.video_artifact import verify_final_pixels


def _make_video(path: Path, source: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", source,
            "-t", "1.2", "-pix_fmt", "yuv420p", str(path),
        ], check=True,
    )


def test_final_pixel_gate_rejects_black_video(tmp_path: Path):
    video = tmp_path / "black.mp4"
    _make_video(video, "color=c=black:s=180x320:r=8")
    result = verify_final_pixels(video)
    assert result["passed"] is False
    assert any(item.startswith("near_black_frame:") for item in result["failures"])
    assert len(result["samples"]) == 3


def test_final_pixel_gate_reads_real_candidate_pixels(tmp_path: Path):
    video = tmp_path / "real.mp4"
    _make_video(video, "testsrc=size=180x320:rate=8")
    result = verify_final_pixels(video)
    assert result["passed"] is True, result
    assert result["candidate_sha256"]
    assert all(item["sha256"] for item in result["samples"])
