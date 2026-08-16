from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_card_title_uses_chinese_text_instead_of_scene_placeholder():
    from scripts.video_toolchain_runner import _card_title

    assert _card_title("中文正文没有空格也应成为卡片标题", 1) != "Scene 2"


def test_card_title_uses_short_english_text_instead_of_scene_placeholder():
    from scripts.video_toolchain_runner import _card_title

    assert _card_title("Ship useful work", 1) == "Ship useful work"


def test_video_artifact_rejects_overlong_short_and_placeholder_title(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "short.mp4"
    video.write_bytes(b"fixture")
    result = verify_artifact(
        video,
        {
            "cards": [{"t": "Scene 1"}],
            "subtitle": {"width": 1080, "height": 1920},
            "motion_score": 0.2,
        },
        "tiktok",
        probe={"width": 1080, "height": 1920, "duration_seconds": 61},
    )

    assert result["passed"] is False
    assert "short_duration_exceeded" in result["failed_dimensions"]
    assert "placeholder_card_title" in result["failed_dimensions"]


def test_video_artifact_rejects_static_or_wrong_vertical_spec(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "vertical.mp4"
    video.write_bytes(b"fixture")
    result = verify_artifact(
        video,
        {
            "cards": [{"t": "A useful implementation checklist"}],
            "subtitle": {"width": 720, "height": 1280},
            "motion_score": 0.001,
        },
        "douyin",
        probe={"width": 720, "height": 1280, "duration_seconds": 30},
    )

    assert result["passed"] is False
    assert "vertical_resolution_invalid" in result["failed_dimensions"]
    assert "subtitle_resolution_invalid" in result["failed_dimensions"]
    assert "motion_evidence_insufficient" in result["failed_dimensions"]


def test_video_artifact_accepts_complete_short_video_evidence(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "valid.mp4"
    video.write_bytes(b"fixture")
    result = verify_artifact(
        video,
        {
            "cards": [{"t": "A useful implementation checklist"}],
            "subtitle": {"width": 1080, "height": 1920},
            "motion_score": 0.2,
        },
        "shipinhao",
        probe={"width": 1080, "height": 1920, "duration_seconds": 45},
    )

    assert result["passed"] is True
    assert result["failed_dimensions"] == []


def test_video_artifact_cli_runs_as_a_direct_script():
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, "scripts/verify_video_artifact.py", "--help"], cwd=root, capture_output=True, text=True, check=False)

    assert process.returncode == 0, process.stderr
    assert "Check final-video dimensions" in process.stdout


def test_motion_evidence_requires_sustained_actual_frame_changes():
    from content_platform.video_artifact import motion_evidence_from_deltas

    animated = motion_evidence_from_deltas([0.03, 0.04, 0.01, 0.05, 0.02, 0.04])
    static = motion_evidence_from_deltas([0.001, 0.002, 0.001, 0.003, 0.001])

    assert animated["passed"] is True
    assert animated["active_ratio"] >= 0.8
    assert static["passed"] is False
