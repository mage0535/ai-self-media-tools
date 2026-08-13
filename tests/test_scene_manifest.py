import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _recipe():
    return {
        "modules": ["cinema_composition_layout", "shotcraft_motion_css", "lower_third_subtitles"],
        "scene_asset_match": [
            {"scene": 1, "script_beat": "Show the problem", "visual_source": "asset-1.jpg", "match_reason": "shows the problem"},
            {"scene": 2, "script_beat": "Explain the method", "visual_source": "asset-2.jpg", "match_reason": "shows the method"},
            {"scene": 3, "script_beat": "Give the action", "visual_source": "asset-3.jpg", "match_reason": "shows the action"},
        ],
    }


def _cards():
    return [
        {"tts": "Show the real problem", "txt": "Show the real problem", "shotcraft": {"name": "establishing"}},
        {"tts": "Explain a practical method", "txt": "Explain a practical method", "shotcraft": {"name": "push_in"}},
        {"tts": "Use this checklist today", "txt": "Use this checklist today", "shotcraft": {"name": "resolve"}},
    ]


def test_scene_manifest_binds_every_scene_to_narration_asset_motion_and_evidence():
    from content_platform.scene_manifest import build_scene_manifest, validate_scene_manifest

    manifest = build_scene_manifest(_cards(), _recipe(), {"platforms": ["douyin"]}, "Useful video")

    assert validate_scene_manifest(manifest)["passed"] is True
    assert manifest["platform"] == "douyin"
    assert len(manifest["scenes"]) == 3
    first = manifest["scenes"][0]
    assert first["narration"] == "Show the real problem"
    assert first["asset"]["source"] == "asset-1.jpg"
    assert first["motion"]["background"]
    assert first["motion"]["subject"] == "establishing"
    assert first["evidence"][0]["match_reason"] == "shows the problem"


def test_scene_manifest_rejects_missing_scene_evidence_and_platform_duration_overrun():
    from content_platform.scene_manifest import build_scene_manifest, validate_rendered_duration, validate_scene_manifest

    manifest = build_scene_manifest(_cards(), _recipe(), {"platforms": ["tiktok"]}, "Useful video")
    manifest["scenes"][1]["evidence"] = []

    validation = validate_scene_manifest(manifest)
    assert validation["passed"] is False
    assert "scene[2] evidence missing" in validation["failures"]

    duration_validation = validate_rendered_duration(build_scene_manifest(_cards(), _recipe(), {"platforms": ["tiktok"]}, "Useful video"), 60.1)
    assert duration_validation["passed"] is False
    assert duration_validation["limit_seconds"] == 60


def test_video_runner_writes_a_valid_scene_manifest_in_dry_run():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "video_toolchain_runner.py"
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "out"
        plan_path = Path(tmp) / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "selected_pipeline": "knowledge_card_video",
                    "content_form": "knowledge_card_video",
                    "template_family": "knowledge_card_motion_case",
                    "platforms": ["tiktok"],
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "VIDEO_OUTPUT_DIR": str(output_dir),
            "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            "VIDEO_TOOLCHAIN_DRY_RUN": "1",
        }
        proc = subprocess.run(
            [sys.executable, str(script), "Hook\nMethod\nChecklist", "Useful video"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        scene_manifest = json.loads((output_dir / "scene_manifest.json").read_text(encoding="utf-8"))
        runner_manifest = json.loads((output_dir / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
        assert scene_manifest["version"] == "scene_manifest_v1"
        assert runner_manifest["scene_manifest_gate"]["passed"] is True


def test_cinema_delivery_rejects_untracked_bgm_and_accepts_an_evidenced_final_artifact():
    from content_platform.cinema_delivery import validate_cinema_delivery
    from content_platform.scene_manifest import build_scene_manifest

    scene_manifest = build_scene_manifest(_cards(), _recipe(), {"platforms": ["douyin"]}, "Useful video")
    probe = {"duration_seconds": 42.0, "width": 1080, "height": 1920, "audio_streams": 1}
    good_bgm = {"source": "licensed_provider", "license": "CC BY 4.0", "sha256": "abc123", "fit_reason": "calm instructional pacing"}

    assert validate_cinema_delivery(scene_manifest, probe, good_bgm)["passed"] is True

    bad_bgm = dict(good_bgm)
    bad_bgm.pop("sha256")
    result = validate_cinema_delivery(scene_manifest, probe, bad_bgm)
    assert result["passed"] is False
    assert "bgm fingerprint missing" in result["failures"]
