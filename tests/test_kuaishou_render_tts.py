import asyncio
import json
import sys
from types import SimpleNamespace

from scripts import kuaishou_render


def test_card_tts_retries_transient_no_audio_and_writes_auditable_config(tmp_path, monkeypatch):
    attempts = []

    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, output):
            attempts.append((self.text, self.voice))
            if len(attempts) == 1:
                raise RuntimeError("temporary no audio")
            with open(output, "wb") as handle:
                handle.write(b"audio" * 4096)

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    monkeypatch.setenv("KUAISHOU_TTS_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr(kuaishou_render, "_duration", lambda _: 2.5, raising=False)

    result = asyncio.run(kuaishou_render.gen_tts(tmp_path, [{"tts": "AI 调用 API 生成 TTS 音频"}]))

    config = json.loads((tmp_path / "tts_config.json").read_text(encoding="utf-8"))
    assert result["rendered"] == 1
    assert len(attempts) == 2
    assert config["segments"][0]["display_text"] == "AI 调用 API 生成 TTS 音频"
    assert config["segments"][0]["tts_text"] != config["segments"][0]["display_text"]
    assert (tmp_path / "tts" / "tts_01.mp3").stat().st_size > 10_000
