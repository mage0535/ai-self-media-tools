import inspect
import json
from pathlib import Path

from scripts import film_renderer, kuaishou_render, render_landscape_video


def test_all_primary_video_renderers_use_the_unified_tts_runtime():
    kuaishou_source = inspect.getsource(kuaishou_render.gen_tts)
    landscape_source = inspect.getsource(render_landscape_video._tts)
    film_source = inspect.getsource(film_renderer.main)

    assert "synthesize_tts_segment" in kuaishou_source
    assert "edge_tts.Communicate" not in kuaishou_source
    assert "synthesize_tts_segment" in landscape_source
    assert "edge_tts.Communicate" not in landscape_source
    assert "synthesize_tts_segment" in film_source
    assert 'get("TTS_PROVIDER", "auto")' in film_source


def test_registry_routes_hojo_before_edge_and_retires_kokoro_from_execution():
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "config" / "creative_capability_registry.json").read_text(encoding="utf-8"))
    capabilities = {row["id"]: row for row in registry["capabilities"]}

    hojo = capabilities["hojo_tts_light_40m"]
    assert hojo["lifecycle"] == "parent_executed"
    assert hojo["parent_id"] == "voice_engine"
    assert hojo["quality_gate"] == "tts_fingerprint_and_audio_gate_v1"
    assert hojo["fallback_chain"] == ["edge_tts"]
    assert capabilities["edge_tts"]["fallback_chain"] == []
    assert capabilities["kokoro"]["lifecycle"] == "inventory_only"
