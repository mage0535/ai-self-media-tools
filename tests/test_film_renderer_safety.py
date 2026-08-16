from pathlib import Path
from unittest.mock import patch

from scripts import film_renderer


ROOT = Path(__file__).resolve().parents[1]


def test_film_renderer_uses_bounded_playwright_recording_and_cleanup():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert 'wait_until="load"' in source
    assert "asyncio.wait_for(_record_shot" in source
    assert "asyncio.wait_for(_record_shot_frames" in source
    assert "await asyncio.wait_for(context.close()" in source
    assert "await asyncio.wait_for(browser.close()" in source


def test_film_renderer_uses_deterministic_still_motion_for_regular_shots():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "async def _render_shot_still" in source
    assert "await render_still(name, str(hp), sd)" in source
    assert '"zoompan=' in source


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
