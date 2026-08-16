from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_film_renderer_uses_bounded_playwright_recording_and_cleanup():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert 'wait_until="load"' in source
    assert "asyncio.wait_for(_record_shot" in source
    assert "await asyncio.wait_for(context.close()" in source
    assert "await asyncio.wait_for(browser.close()" in source
