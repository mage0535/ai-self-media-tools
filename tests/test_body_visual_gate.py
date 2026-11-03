"""The rejected Douyin body cards must fail closed on every listed platform."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from content_platform.body_visual_gate import (
    BACKGROUND_EMPTY_OR_SOLID,
    BODY_VISUAL_EVIDENCE_MISSING,
    BODY_VISUAL_PLATFORMS,
    MOTION_FALLBACK_BLOCKS_QUALIFIED,
    SUBTITLE_LAYOUT_UNREADABLE,
    TEXT_OVERFLOW_FRAME,
    assess_handoff_preflight,
    delivery_verdict,
    evaluate_body_visual,
    evaluate_frames,
    platform_requires_body_visual,
    _decode_frame,
)
from content_platform.cinema_delivery import validate_cinema_delivery
from content_platform.pipeline import Pipeline
from content_platform.preflight_manifest import validate_preflight_manifest
from content_platform.scene_manifest import build_scene_manifest
from content_platform.video_artifact import verify_artifact
from tests.scene_fixture import write_color_scene_mp4

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "body_visual"
REJECTED_MP4 = Path("/home/ubuntu/.cursor/projects/workspace/uploads/BI-mfg-sop-douyin-20261103_v1_409d.mp4")
REJECTED_SHA256 = "0de3e6276acdc12865f5e3627b52aca60ef14ffcaeb4d7e41b752f6990d1e854"
REQUIRED_PLATFORMS = {"douyin", "shipinhao", "kuaishou", "xiaohongshu", "youtube", "tiktok", "bilibili"}


def _fixture_frames():
    frames = [_decode_frame(path, None) for path in sorted(FIXTURE_DIR.glob("body_*.jpg"))]
    assert frames and all(frame is not None for frame in frames)
    return frames


def _loop_fixture_mp4(destination: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(FIXTURE_DIR / "body_15s.jpg"),
            "-t",
            "6",
            "-r",
            "8",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ],
        check=True,
    )


def _assert_rejected_codes(result: dict) -> None:
    assert result["passed"] is False
    assert BACKGROUND_EMPTY_OR_SOLID in result["failed_codes"]
    assert TEXT_OVERFLOW_FRAME in result["failed_codes"]
    assert SUBTITLE_LAYOUT_UNREADABLE in result["failed_codes"]


def test_rejected_body_frames_fail_background_overflow_and_subtitle():
    _assert_rejected_codes(evaluate_frames(_fixture_frames(), platform="douyin"))


def test_looped_rejected_frame_mp4_fails_sampled_delivery_gate(tmp_path: Path):
    video = tmp_path / "rejected-body.mp4"
    _loop_fixture_mp4(video)
    for platform in REQUIRED_PLATFORMS:
        result = evaluate_body_visual(video, platform=platform)
        _assert_rejected_codes(result)


def test_original_rejected_douyin_mp4_fails_when_present():
    if not REJECTED_MP4.is_file():
        pytest.skip("original rejected mp4 is not mounted")
    digest = hashlib.sha256(REJECTED_MP4.read_bytes()).hexdigest()
    assert digest == REJECTED_SHA256
    result = evaluate_body_visual(REJECTED_MP4, platform="douyin")
    _assert_rejected_codes(result)
    artifact = verify_artifact(
        REJECTED_MP4,
        {
            "cards": [{"t": "停机后先隔离能量"}],
            "subtitle": {"width": 1080, "height": 1920},
            "motion_score": 0.2,
            "MOTION_FALLBACK": "kf_freeze_vertical",
        },
        "douyin",
    )
    assert artifact["passed"] is False
    assert artifact["delivery_verdict"] == "fail"
    assert artifact["qualified"] is False
    assert artifact["preflight_status"] == "FAIL"
    for code in (BACKGROUND_EMPTY_OR_SOLID, TEXT_OVERFLOW_FRAME, MOTION_FALLBACK_BLOCKS_QUALIFIED):
        assert code in artifact["failed_dimensions"]


def test_color_scene_passes_and_kf_freeze_still_blocks_handoff(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    write_color_scene_mp4(video)
    visual = evaluate_body_visual(video, platform="kuaishou")
    assert visual["passed"] is True
    assert visual["failed_codes"] == []

    manifest = {
        "cards": [{"t": "A useful implementation checklist"}],
        "subtitle": {"width": 1080, "height": 1920},
        "motion_score": 0.2,
    }
    probe = {"width": 1080, "height": 1920, "duration_seconds": 45}
    passed = verify_artifact(video, manifest, "shipinhao", probe=probe)
    assert passed["passed"] is True
    assert passed["delivery_verdict"] == "pass"
    assert passed["preflight_status"] == "PASS"
    assert passed["qualified"] is True

    frozen = verify_artifact(video, {**manifest, "MOTION_FALLBACK": "kf_freeze_vertical"}, "tiktok", probe=probe)
    assert frozen["passed"] is False
    assert frozen["delivery_verdict"] == "fail"
    assert frozen["qualified"] is False
    assert frozen["preflight_status"] == "FAIL"
    assert MOTION_FALLBACK_BLOCKS_QUALIFIED in frozen["failed_dimensions"]
    assert BACKGROUND_EMPTY_OR_SOLID not in frozen["failed_dimensions"]


def test_motion_exemption_cannot_justify_delivery_pass():
    verdict = delivery_verdict(
        technical_passed=True,
        body_visual={"passed": True, "failed_codes": []},
        motion_exempted=True,
    )
    assert verdict["delivery_verdict"] == "fail"
    assert verdict["qualified"] is False
    assert verdict["preflight_status"] == "FAIL"
    assert MOTION_FALLBACK_BLOCKS_QUALIFIED in verdict["failed_codes"]

    missing = delivery_verdict(technical_passed=True, body_visual=None)
    assert missing["delivery_verdict"] == "fail"
    assert BODY_VISUAL_EVIDENCE_MISSING in missing["failed_codes"]


def test_preflight_handoff_rejects_kf_freeze_even_without_a_manifest():
    packet = {"platform": "bilibili", "MOTION_FALLBACK": "kf_freeze_vertical"}
    preflight = validate_preflight_manifest(packet, "bilibili")
    assert preflight["passed"] is False
    assert MOTION_FALLBACK_BLOCKS_QUALIFIED in preflight["failed_dimensions"]
    handoff = assess_handoff_preflight(packet)
    assert handoff["preflight_status"] == "FAIL"
    assert handoff["qualified"] is False


def test_listed_platforms_require_the_body_gate():
    assert REQUIRED_PLATFORMS <= BODY_VISUAL_PLATFORMS
    for platform in REQUIRED_PLATFORMS:
        assert platform_requires_body_visual(platform)
    assert platform_requires_body_visual("douyin_ai")
    assert platform_requires_body_visual("rednote")
    assert platform_requires_body_visual("wechat") is False


def test_rendered_gate_rejects_freeze_and_solid_body(tmp_path: Path):
    scene = tmp_path / "scene.mp4"
    write_color_scene_mp4(scene)
    rejected = tmp_path / "rejected.mp4"
    _loop_fixture_mp4(rejected)
    planned = [
        "cinema_composition.storyboard",
        "shotcraft_moves.shot_plan_for_text",
        "kuaishou_render.render_cards",
        "kuaishou_render.download_bgm",
        "kuaishou_render.gen_subtitles",
        "kuaishou_render.encode_final",
    ]

    def packet(path: Path, **extra_manifest):
        return {
            "video_toolchain_plan": {"required": True, "platforms": ["douyin", "youtube", "bilibili", "xiaohongshu"]},
            "video_artifact": {"path": str(path)},
            "render_manifest": {
                "ok": True,
                "status": "rendered",
                "output": str(path),
                "toolchain_contract": {"planned_tools": planned},
                "motion_evidence": {"passed": True, "unique_frame_count": 4},
                "segment_motion_evidence": {
                    "segments": [
                        {"move_id": "one", "profile": "hero"},
                        {"move_id": "two", "profile": "demo"},
                        {"move_id": "three", "profile": "cta"},
                    ]
                },
                **extra_manifest,
            },
            "audio_probe": {"stream_count": 1, "duration": 45},
            "bgm_source": {
                "source": "licensed_piano",
                "source_url": "https://example.test/bgm",
                "license": "CC-BY",
                "fit_reason": "calm tutorial",
            },
            "subtitle": {"cue_count": 8},
            "burned_captions": {
                "position": "lower_third",
                "burned_in": True,
                "font_size": 48,
                "max_chars_per_line": 18,
                "max_lines": 2,
                "margin_v": 200,
            },
            "background_assets": [{"path": f"bg-{index}.png"} for index in range(4)],
        }

    frozen = Pipeline._rendered_video_platform_gate(packet(scene, MOTION_FALLBACK="kf_freeze_vertical"), "youtube")
    assert frozen["passed"] is False
    assert frozen["delivery_verdict"] == "fail"
    assert frozen["qualified"] is False
    assert frozen["preflight_status"] == "FAIL"
    assert MOTION_FALLBACK_BLOCKS_QUALIFIED in frozen["failed_dimensions"]

    solid = Pipeline._rendered_video_platform_gate(packet(rejected), "bilibili")
    assert solid["passed"] is False
    assert solid["delivery_verdict"] == "fail"
    assert BACKGROUND_EMPTY_OR_SOLID in solid["failed_dimensions"]
    assert TEXT_OVERFLOW_FRAME in solid["failed_dimensions"]

    clean = Pipeline._rendered_video_platform_gate(packet(scene), "xiaohongshu")
    assert clean["passed"] is True
    assert clean["delivery_verdict"] == "pass"
    assert clean["qualified"] is True
    assert clean["preflight_status"] == "PASS"


def test_cinema_delivery_samples_video_path(tmp_path: Path):
    video = tmp_path / "rejected.mp4"
    _loop_fixture_mp4(video)
    recipe = {
        "modules": ["cinema_composition_layout", "shotcraft_motion_css", "lower_third_subtitles"],
        "scene_asset_match": [
            {"scene": 1, "script_beat": "Show the problem", "visual_source": "asset-1.jpg", "match_reason": "shows the problem"},
            {"scene": 2, "script_beat": "Explain the method", "visual_source": "asset-2.jpg", "match_reason": "shows the method"},
            {"scene": 3, "script_beat": "Give the action", "visual_source": "asset-3.jpg", "match_reason": "shows the action"},
        ],
    }
    cards = [
        {"tts": "Show the real problem", "txt": "Show the real problem", "shotcraft": {"name": "establishing"}},
        {"tts": "Explain a practical method", "txt": "Explain a practical method", "shotcraft": {"name": "push_in"}},
        {"tts": "Use this checklist today", "txt": "Use this checklist today", "shotcraft": {"name": "resolve"}},
    ]
    scene_manifest = build_scene_manifest(cards, recipe, {"platforms": ["douyin"]}, "Useful video")
    probe = {
        "duration_seconds": 42.0,
        "width": 1080,
        "height": 1920,
        "audio_streams": 1,
        "sample_rate": 44100,
        "channels": 2,
        "path": str(video),
    }
    bgm = {"source": "licensed_provider", "license": "CC BY 4.0", "sha256": "abc123", "fit_reason": "calm instructional pacing"}
    result = validate_cinema_delivery(scene_manifest, probe, bgm, {"passed": True}, {"passed": True})
    assert result["passed"] is False
    assert result["delivery_verdict"] == "fail"
    assert result["qualified"] is False
    assert BACKGROUND_EMPTY_OR_SOLID in result["failures"]
    assert TEXT_OVERFLOW_FRAME in result["failures"]
