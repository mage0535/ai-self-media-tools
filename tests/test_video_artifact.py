from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def _real_video(path: Path, size: str = "720x1280") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=8", "-t", "2", "-an", str(path)],
        check=True,
        capture_output=True,
    )

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
        probe={"width": 1080, "height": 1920, "duration_seconds": 160},
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
        "tiktok",
        probe={"width": 720, "height": 1280, "duration_seconds": 30},
    )

    assert result["passed"] is False
    assert "vertical_resolution_invalid" in result["failed_dimensions"]
    assert "motion_measurement_failed" in result["failed_dimensions"]


def test_video_artifact_rejects_subtitle_dimensions_that_do_not_match_video(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "mismatch.mp4"
    video.write_bytes(b"fixture")
    result = verify_artifact(
        video,
        {
            "cards": [{"t": "工业质检人工接管流程"}],
            "subtitle": {"width": 1080, "height": 1920},
            "motion_score": 0.2,
        },
        "douyin",
        probe={"width": 720, "height": 1280, "duration_seconds": 45},
    )

    assert result["passed"] is False
    assert "subtitle_resolution_invalid" in result["failed_dimensions"]


def test_video_artifact_accepts_douyin_720x1280_with_matching_subtitles(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "douyin.mp4"
    _real_video(video)
    result = verify_artifact(
        video,
        {
            "cards": [{"t": "工业质检人工接管流程"}],
            "subtitle": {"width": 720, "height": 1280},
            "motion_score": 0.2,
        },
        "douyin",
        probe={"width": 720, "height": 1280, "duration_seconds": 69.6},
    )

    assert result["passed"] is True
    assert result["failed_dimensions"] == []


def test_video_artifact_accepts_complete_short_video_evidence(tmp_path: Path):
    from content_platform.video_artifact import verify_artifact

    video = tmp_path / "valid.mp4"
    _real_video(video, "1080x1920")
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
    from content_platform.video_artifact import MOTION_EVIDENCE_VERSION, motion_evidence_from_deltas

    animated = motion_evidence_from_deltas([0.03, 0.04, 0.01, 0.05, 0.02, 0.04])
    static = motion_evidence_from_deltas([0.001, 0.002, 0.001, 0.003, 0.001])
    smooth_cinematic = motion_evidence_from_deltas([0.012] * 9 + [0.03] * 3)

    assert animated["passed"] is True
    assert animated["active_ratio"] >= 0.8
    assert static["passed"] is False
    assert smooth_cinematic["passed"] is True
    assert smooth_cinematic["sustained_motion_ratio"] >= 0.85
    assert MOTION_EVIDENCE_VERSION == "sustained-v2"


def test_spatial_motion_excludes_only_short_isolated_transition_bursts():
    from content_platform.video_artifact import _exclude_short_global_transition_bursts

    background = [0.001] * 10 + [0.11, 0.13, 0.10] + [0.001] * 10
    moving_area = [0.01] * 10 + [0.7, 0.8, 0.7] + [0.01] * 10
    result = _exclude_short_global_transition_bursts(background, moving_area, sample_fps=4)

    assert result["clusters"] == [[10, 12]]
    assert {9, 10, 11, 12, 13} <= set(result["excluded_indices"])


def test_spatial_motion_never_excludes_sustained_global_motion():
    from content_platform.video_artifact import _exclude_short_global_transition_bursts

    background = [0.08] * 12
    moving_area = [0.75] * 12
    result = _exclude_short_global_transition_bursts(background, moving_area, sample_fps=4)

    assert result["clusters"] == [[0, 11]]
    assert result["excluded_indices"] == []
