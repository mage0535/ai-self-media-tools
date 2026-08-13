import json
from pathlib import Path
from unittest.mock import patch


def test_voice_engine_writes_display_and_tts_text_and_updates_scene_timing(tmp_path: Path):
    from scripts.voice_engine import EdgeTTSProvider, VoiceEngine

    manifest = {
        "version": "scene_manifest_v1",
        "scenes": [{"scene_id": "s01"}, {"scene_id": "s02"}],
    }
    (tmp_path / "scene_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    async def fake_tts(text, output, voice, rate="+0%", pitch="+0Hz"):
        output.write_bytes(b"audio")
        return [{"word": text, "start": 0.0, "end": 1.0}]

    def fake_duration(path):
        return 1.0 if "seg_" in str(path) else 2.0

    def fake_ffmpeg(*args, **kwargs):
        Path(args[0][-1]).write_bytes(b"final audio" * 20)

    with patch.object(EdgeTTSProvider, "synthesize_with_timing", new=staticmethod(fake_tts)), patch.object(
        EdgeTTSProvider, "_get_duration", side_effect=fake_duration
    ), patch("scripts.voice_engine.DeAIProcessor.apply") as deai, patch("scripts.voice_engine.subprocess.run", side_effect=fake_ffmpeg):
        def fake_deai(source, output, durations, lang):
            output.write_bytes(b"wav")
            return output

        deai.side_effect = fake_deai
        result = VoiceEngine(tmp_path).synthesize("AI 调用 API。第二段。", lang="zh", genre="tech", mode="single")

    config = json.loads((tmp_path / "tts_config.json").read_text(encoding="utf-8"))
    updated = json.loads((tmp_path / "scene_manifest.json").read_text(encoding="utf-8"))
    assert result["subtitle"].endswith("narration.srt")
    assert config["segments"][0]["display_text"] == "AI 调用 API。"
    assert config["segments"][0]["tts_text"] == "人工智能 调用 A P I。"
    assert updated["audio_timing"]["total_duration_seconds"] == 2.0
