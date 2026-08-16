import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import film_renderer


ROOT = Path(__file__).resolve().parents[1]


def test_film_renderer_uses_bounded_playwright_recording_and_cleanup():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert 'wait_until="load"' in source
    assert "asyncio.wait_for(_record_shot" in source
    assert "asyncio.wait_for(_record_shot_frames" in source
    assert "await asyncio.wait_for(context.close()" in source
    assert "await asyncio.wait_for(browser.close()" in source


def test_default_policy_requires_cinematic_motion(monkeypatch):
    monkeypatch.delenv("FILM_QUALITY_PROFILE", raising=False)
    monkeypatch.delenv("FILM_MOTION_MODE", raising=False)
    monkeypatch.delenv("FILM_ALLOW_DEGRADED", raising=False)

    policy = film_renderer.resolve_render_policy()

    assert policy == {"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False}


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
