import hashlib

from content_platform.adapter_executor import execute_capability
from scripts.film_renderer import build_scene_effect_evidence


def _scene(tmp_path, index=1):
    asset = tmp_path / f"asset-{index}.png"
    asset.write_bytes(f"asset-{index}".encode())
    return {
        "scene_id": f"s{index:02d}",
        "display_purpose": "explain",
        "asset_path": str(asset),
        "asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        "camera_language": "handheld_push",
        "camera_index": 0,
        "subject_motion": "kanban_reveal",
        "element_shot": "tile_activate",
        "text_motion": "message_type",
        "text_motion_index": 0,
        "transition": "fadeblack",
        "declared_transition": "hard_cut",
        "actual_transition_after": "fadeblack",
        "rhythm_beat": {"emphasis": "proof"},
        "interaction_prompt": "",
        "renderer_modes": ["playwright-video", "playwright-frame-video"],
        "fallback": False,
        "reused": False,
        "motion_probe": {"passed": True, "mean_delta": 0.04, "static_ratio": 0.2},
    }


def test_scene_effect_evidence_binds_plan_and_probe_to_final_video(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")

    evidence = build_scene_effect_evidence(final, [_scene(tmp_path)], quality_profile="high", expected_scene_count=1)

    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    assert evidence["passed"] is True
    assert evidence["artifact_sha256"] == digest
    assert evidence["effect_evidence"] == {
        "passed": True,
        "artifact_sha256": digest,
        "probe": "scene_motion_and_director_mapping",
        "scene_count": 1,
    }


def test_scene_effect_evidence_rejects_missing_motion_and_transition_mapping(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")
    scene = _scene(tmp_path)
    scene["motion_probe"] = {"passed": False}
    scene["actual_transition_after"] = "wipeleft"

    evidence = build_scene_effect_evidence(final, [scene], quality_profile="high", expected_scene_count=1)

    assert evidence["passed"] is False
    assert "s01:motion_probe_failed" in evidence["failures"]
    assert "s01:transition_not_applied" in evidence["failures"]
    assert evidence["effect_evidence"]["passed"] is False


def test_scene_effect_evidence_rejects_asset_hash_mismatch_and_fallback(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")
    scene = _scene(tmp_path)
    scene["asset_sha256"] = "0" * 64
    scene["fallback"] = True

    evidence = build_scene_effect_evidence(final, [scene], quality_profile="high", expected_scene_count=1)

    assert "s01:asset_hash_mismatch" in evidence["failures"]
    assert "s01:cinematic_fallback" in evidence["failures"]


def test_video_capability_executes_only_with_final_bound_scene_effect(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")
    scene_evidence = build_scene_effect_evidence(
        final, [_scene(tmp_path)], quality_profile="high", expected_scene_count=1
    )
    capability = {
        "id": "video_toolchain_runner",
        "kind": "tool",
        "lifecycle": "executable",
        "adapter": "python:content_platform.adapters.runtime:execute",
        "availability_probe": "module:content_platform.adapters.runtime",
        "required_inputs": ["content_profile", "content_blueprint"],
        "output_contract": "video_template_plan_v1",
    }

    result = execute_capability(
        capability,
        {
            "content_profile": {"content_format": "short_video"},
            "content_blueprint": {"topic": "AI workflow"},
            "render_manifest": {"status": "rendered", "ok": True, "output": str(final)},
            "scene_execution_evidence": scene_evidence,
        },
    )

    assert result["status"] == "executed"
    assert result["output"]["artifact_evidence"][0]["sha256"] == hashlib.sha256(final.read_bytes()).hexdigest()
    assert result["output"]["effect_evidence"]["passed"] is True


def test_video_capability_rejects_scene_effect_for_another_artifact(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")
    scene_evidence = build_scene_effect_evidence(
        final, [_scene(tmp_path)], quality_profile="high", expected_scene_count=1
    )
    scene_evidence["artifact_sha256"] = "0" * 64
    capability = {
        "id": "video_toolchain_runner",
        "kind": "tool",
        "lifecycle": "executable",
        "adapter": "python:content_platform.adapters.runtime:execute",
        "availability_probe": "module:content_platform.adapters.runtime",
        "required_inputs": ["content_profile", "content_blueprint"],
        "output_contract": "video_template_plan_v1",
    }

    result = execute_capability(
        capability,
        {
            "content_profile": {"content_format": "short_video"},
            "content_blueprint": {"topic": "AI workflow"},
            "render_manifest": {"status": "rendered", "ok": True, "output": str(final)},
            "scene_execution_evidence": scene_evidence,
        },
    )

    assert result["status"] == "failed"
    assert "scene_effect_not_verified" in result["output"]["reason"]
