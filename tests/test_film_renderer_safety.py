import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import film_renderer


ROOT = Path(__file__).resolve().parents[1]


def test_film_renderer_uses_bounded_playwright_recording_and_cleanup():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert 'wait_until="load"' in source
    assert "_record_shot(name, html_path, duration, out, frame_driven=frame_driven)" in source
    assert "element_render_timeout_seconds(duration)" in source
    assert "frame_driven: bool = False" in source
    assert "requestAnimationFrame(tick)" in source
    assert "await asyncio.wait_for(context.close()" in source
    assert "await asyncio.wait_for(browser.close()" in source


def test_default_policy_requires_cinematic_motion(monkeypatch):
    monkeypatch.delenv("FILM_QUALITY_PROFILE", raising=False)
    monkeypatch.delenv("FILM_MOTION_MODE", raising=False)
    monkeypatch.delenv("FILM_ALLOW_DEGRADED", raising=False)

    policy = film_renderer.resolve_render_policy()

    assert policy == {"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False}


def test_renderer_rejects_empty_platform_gate_bypass():
    with pytest.raises(ValueError, match="non-empty video platform"):
        film_renderer.validate_platform_argument("")
    assert film_renderer.validate_platform_argument("youtube-shorts") == "youtube_shorts"


def test_scene_static_ratio_uses_sustained_motion_not_strong_activity():
    motion = {"active_ratio": 0.0, "sustained_motion_ratio": 0.55}
    assert film_renderer.scene_static_ratio(motion) == 0.45


def test_element_frame_render_timeout_covers_high_resolution_long_scenes():
    assert film_renderer.element_render_timeout_seconds(10.82) >= 90
    assert film_renderer.RENDERER_VERSION == "cinematic-v10"


def test_safe_motion_requires_explicit_degraded_opt_in(monkeypatch):
    monkeypatch.setenv("FILM_QUALITY_PROFILE", "degraded")
    monkeypatch.setenv("FILM_MOTION_MODE", "safe")
    monkeypatch.delenv("FILM_ALLOW_DEGRADED", raising=False)

    with pytest.raises(ValueError, match="FILM_ALLOW_DEGRADED"):
        film_renderer.resolve_render_policy()


def test_changed_render_contract_invalidates_stale_shots(tmp_path):
    old_contract = {"renderer_version": "cinematic-v1", "motion_mode": "cinematic"}
    (tmp_path / "render_contract.json").write_text(json.dumps(old_contract), encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    stale_shot = shots / "shot_01A.mp4"
    stale_shot.write_bytes(b"stale")
    stale_final = tmp_path / "final.mp4"
    stale_final.write_bytes(b"stale")

    changed = film_renderer.prepare_render_contract(
        tmp_path,
        {"renderer_version": "cinematic-v2", "motion_mode": "cinematic"},
    )

    assert changed is True
    assert not stale_shot.exists()
    assert not stale_final.exists()


def test_cinematic_quality_rejects_still_fallback():
    evidence = film_renderer.build_render_quality_evidence(
        policy={"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False},
        shot_records=[{"name": "shot_01A", "renderer": "still-motion", "fallback": True}],
        motion={"mean_delta": 0.03, "active_ratio": 0.9, "peak_count": 5, "passed": True},
    )

    assert evidence["passed"] is False
    assert "cinematic_fallback_used" in evidence["failures"]


def test_audio_spec_requires_44100hz_stereo():
    assert film_renderer.validate_audio_spec({"sample_rate": 24000, "channels": 1})["passed"] is False
    assert film_renderer.validate_audio_spec({"sample_rate": 44100, "channels": 2})["passed"] is True


def test_timeline_uses_real_transition_boundaries():
    starts, total = film_renderer.calculate_timeline([2.0, 2.0, 2.0], [0.35, 0.0])

    assert starts == [0.0, 1.65, 3.65]
    assert total == 5.65


def test_segment_shot_budget_covers_internal_crossfade_and_audio_margin():
    a_duration, b_duration = film_renderer.segment_shot_durations(9.38, element_motion=False)

    assert a_duration + b_duration - film_renderer.XFADE_DUR_LONG >= 9.53


def test_cinematic_templates_use_continuous_high_frequency_background_motion():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "animation: kb 6s linear infinite alternate" in source
    assert '"motion_evidence_version": MOTION_EVIDENCE_VERSION' in source


def test_screenshot_shots_keep_moving_after_their_entrance_animation():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "@keyframes screenshotFloat" in source
    assert "screenshotFloat 5.2s linear 0.9s infinite alternate" in source


def test_cinematic_establishing_shots_use_multiple_compositions_and_pet_documentary_mode():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "content_styles = [" in source
    assert "title_sizes = [80, 64, 70, 62]" in source
    assert 'platform).casefold() == "douyin_pet"' in source
    assert "platform=args.platform" in source


def test_visual_treatment_rejects_scene_without_required_directives(tmp_path):
    plan = {
        "version": "visual_treatment_plan_v1",
        "scenes": [{"scene_id": "s01", "display_purpose": "hook"}],
    }
    path = tmp_path / "visual_treatment_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        film_renderer.load_visual_treatment_plan(path, expected_scene_count=1)


def test_visual_treatment_maps_plan_to_real_renderer_choices(tmp_path):
    asset = tmp_path / "proof.png"
    asset.write_bytes(b"asset")
    plan = {
        "version": "visual_treatment_plan_v1",
        "scenes": [{
            "scene_id": "s01",
            "display_purpose": "show proof",
            "real_asset": str(asset),
            "camera_language": "left_dolly",
            "subject_motion": "action_path",
            "text_motion": "before_after_wipe",
            "transition": "left_swipe",
            "rhythm_beat": {"emphasis": "proof"},
            "interaction_prompt": "comment",
        }],
    }
    path = tmp_path / "visual_treatment_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    scene = film_renderer.load_visual_treatment_plan(path, expected_scene_count=1)[0]
    applied = film_renderer.resolve_scene_treatment(scene)

    assert applied["camera_index"] == 1
    assert applied["element_shot"] == "step_light"
    assert applied["transition"] == "slideleft"
    assert applied["asset_sha256"] == film_renderer._sha256_file(asset)


def test_visual_treatment_never_selects_unsupported_xfade_transition():
    supported = {"fadeblack", "smoothleft", "circleopen", "slideleft", "wipeleft", "smoothup", "revealright"}

    assert set(film_renderer.TRANSITION_MAP.values()).issubset(supported)


def test_visual_treatment_builder_creates_complete_unique_scene_plan(tmp_path):
    backgrounds = []
    for index in range(8):
        path = tmp_path / f"bg_{index:02d}.jpg"
        path.write_bytes(f"background-{index}".encode())
        backgrounds.append(path)

    generated = film_renderer.ensure_visual_treatment_plan(tmp_path, backgrounds)
    scenes = film_renderer.load_visual_treatment_plan(generated, expected_scene_count=8)

    assert generated.is_file()
    assert len({scene["camera_language"] for scene in scenes}) >= 6
    assert len({scene["transition"] for scene in scenes}) >= 4


def test_high_quality_profile_does_not_accept_a_failed_script_gate():
    assert film_renderer.script_gate_passed(0, "high") is True
    assert film_renderer.script_gate_passed(1, "high") is False
    assert film_renderer.script_gate_passed(1, "degraded") is True


def test_film_renderer_retries_edge_tts_and_rejects_empty_audio(tmp_path, monkeypatch):
    output = tmp_path / "voice.mp3"
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 2:
            output.write_bytes(b"audio" * 4096)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setenv("FILM_TTS_RETRY_DELAY_SECONDS", "0")
    with patch("scripts.film_renderer.subprocess.run", side_effect=fake_run):
        attempts = film_renderer.synthesize_edge_tts("人工智能", output, "zh-CN-YunjianNeural")

    assert attempts == 2
    assert len(calls) == 2
    assert output.stat().st_size > 10_000
