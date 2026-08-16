import asyncio
import json
import sys
import time
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


def test_card_tts_times_out_each_attempt_instead_of_hanging(tmp_path, monkeypatch):
    class HungCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, output):
            await asyncio.sleep(1)

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=HungCommunicate))
    monkeypatch.setenv("KUAISHOU_TTS_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("KUAISHOU_TTS_ATTEMPT_TIMEOUT_SECONDS", "0.01")

    try:
        asyncio.run(kuaishou_render.gen_tts(tmp_path, [{"tts": "等待超时测试"}]))
    except RuntimeError as exc:
        assert "timeout" in str(exc)
    else:  # pragma: no cover - makes an unexpected successful network wait explicit
        raise AssertionError("hung TTS call must fail closed")


def test_bgm_download_fails_before_opening_network_when_budget_is_exhausted(tmp_path, monkeypatch):
    calls = []

    def should_not_open(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("expired BGM budget must not open a network request")

    monkeypatch.setattr(kuaishou_render.urllib.request, "urlopen", should_not_open)
    monkeypatch.setattr(kuaishou_render, "_ACTIVE_BGM_DEADLINE", time.monotonic() - 1)

    try:
        kuaishou_render._download_candidate_bgm(
            {"download_url": "https://example.invalid/audio.mp3"},
            tmp_path / "bgm.mp3",
        )
    except TimeoutError as exc:
        assert "budget" in str(exc)
    else:  # pragma: no cover - makes a deadline regression explicit
        raise AssertionError("expired BGM budget must fail closed")
    assert calls == []


def test_bgm_download_limits_each_candidate_without_consuming_global_budget(tmp_path, monkeypatch):
    candidate = {
        "provider": "pixabay_music",
        "download_url": "https://cdn.example/acoustic-guitar.mp3",
        "source_url": "https://pixabay.example/acoustic-guitar",
        "title": "Acoustic guitar instrumental",
        "artist": "artist",
        "license": "Pixabay Content License",
        "tags": "acoustic guitar instrumental",
        "license_verified": True,
    }
    candidate_deadlines = []

    def fake_download(_candidate, output):
        candidate_deadlines.append(kuaishou_render._ACTIVE_BGM_CANDIDATE_DEADLINE)
        output.write_bytes(b"audio" * 200_000)

    started = time.monotonic()
    monkeypatch.setenv("BGM_RESOLUTION_MAX_SECONDS", "90")
    monkeypatch.setenv("BGM_CANDIDATE_MAX_SECONDS", "3")
    monkeypatch.setenv("BGM_FINGERPRINT_REGISTRY", str(tmp_path / "bgm_registry.json"))
    monkeypatch.setattr(kuaishou_render, "_online_bgm_candidates", lambda _style: [candidate])
    monkeypatch.setattr(kuaishou_render, "_download_candidate_bgm", fake_download)

    kuaishou_render.download_bgm(tmp_path, "acoustic guitar")

    assert len(candidate_deadlines) == 1
    assert candidate_deadlines[0] is not None
    assert 0 < candidate_deadlines[0] - started <= 3.5
