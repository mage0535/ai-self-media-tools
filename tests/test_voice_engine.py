import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.voice_engine import QwenTTSProvider
from scripts.voice_engine import VoiceEngine, select_tts_provider


class _Response:
    def __init__(self, *, status_code=200, payload=None, content=b"audio"):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = "ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class QwenTTSProviderTests(unittest.TestCase):
    def test_auto_provider_keeps_edge_until_qwen_quality_is_approved(self):
        with patch.dict("os.environ", {"QWEN_TTS_QUALITY_APPROVED": "false"}, clear=False):
            self.assertEqual(select_tts_provider("auto", qwen_available=True, language="zh"), "edge")
        with patch.dict("os.environ", {"QWEN_TTS_QUALITY_APPROVED": "true", "TTS_AB_TEST_APPROVED_PROVIDER": "qwen"}, clear=False):
            self.assertEqual(select_tts_provider("auto", qwen_available=True, language="zh"), "qwen")

    def test_provider_downloads_audio_url_and_writes_manifest(self):
        payload = {
            "status_code": 200,
            "request_id": "req-1",
            "output": {"audio": {"url": "https://example.test/audio.wav", "id": "audio-1"}},
            "usage": {"characters": 12},
        }
        calls = []

        def fake_post(url, **kwargs):
            calls.append(("post", url, kwargs))
            return _Response(payload=payload)

        def fake_get(url, **kwargs):
            calls.append(("get", url, kwargs))
            return _Response(content=b"RIFF" + (b"fake-audio" * 20))

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "narration.wav"
            provider = QwenTTSProvider(api_key="test-key", model="qwen3-tts-flash", timeout=7)
            with patch("scripts.voice_engine.requests.post", side_effect=fake_post), patch(
                "scripts.voice_engine.requests.get", side_effect=fake_get
            ):
                result = provider.synthesize("hello", out, voice="Cherry", language="English")

            self.assertTrue(out.read_bytes().startswith(b"RIFFfake-audio"))
            self.assertEqual(result["provider"], "qwen3-tts")
            self.assertEqual(result["model"], "qwen3-tts-flash")
            self.assertEqual(result["request_id"], "req-1")
            self.assertEqual(result["usage"]["characters"], 12)
            self.assertEqual(calls[0][0], "post")
            self.assertEqual(calls[1], ("get", "https://example.test/audio.wav", {"timeout": 7}))

    def test_provider_tries_model_chain_before_returning_audio(self):
        calls = []

        def fake_post(url, **kwargs):
            calls.append(kwargs["json"]["model"])
            if len(calls) == 1:
                return _Response(status_code=429, payload={"status_code": 429, "message": "quota exhausted"})
            return _Response(
                payload={
                    "status_code": 200,
                    "request_id": "req-2",
                    "output": {"audio": {"url": "https://example.test/audio.wav"}},
                    "usage": {"characters": 5},
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "narration.wav"
            provider = QwenTTSProvider(
                api_key="test-key",
                model="qwen-audio-3.0-tts-flash,qwen-audio-3.0-tts-plus",
                timeout=7,
            )
            with patch("scripts.voice_engine.requests.post", side_effect=fake_post), patch(
                "scripts.voice_engine.requests.get",
                return_value=_Response(content=b"RIFF" + (b"fake-audio" * 20)),
            ):
                result = provider.synthesize("hello", out, voice="Cherry", language="English")

        self.assertEqual(calls, ["qwen-audio-3.0-tts-flash", "qwen-audio-3.0-tts-plus"])
        self.assertEqual(result["model"], "qwen-audio-3.0-tts-plus")
        self.assertEqual(result["model_attempts"][0]["model"], "qwen-audio-3.0-tts-flash")

    def test_audio_series_models_use_speech_synthesizer_endpoint(self):
        payload = {
            "request_id": "req-audio",
            "output": {"audio": {"url": "https://example.test/audio.mp3"}},
            "usage": {"characters": 8},
        }
        seen = {}

        def fake_post(url, **kwargs):
            seen["url"] = url
            seen["body"] = kwargs["json"]
            return _Response(payload=payload)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "narration.mp3"
            provider = QwenTTSProvider(api_key="test-key", model="qwen-audio-3.0-tts-flash", timeout=7)
            with patch("scripts.voice_engine.requests.post", side_effect=fake_post), patch(
                "scripts.voice_engine.requests.get",
                return_value=_Response(content=b"ID3" + (b"fake-audio" * 20)),
            ):
                result = provider.synthesize("hello", out, voice="Cherry", language="English")

        self.assertTrue(seen["url"].endswith("/services/audio/tts/SpeechSynthesizer"))
        self.assertEqual(seen["body"]["input"]["voice"], "longanhuan_v3.6")
        self.assertEqual(seen["body"]["input"]["format"], "mp3")
        self.assertEqual(result["model"], "qwen-audio-3.0-tts-flash")

    def test_voice_engine_encodes_audio_returned_by_deai_processor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback_audio = root / "concat.wav"
            fallback_audio.write_bytes(b"RIFF" + b"0" * 256)

            def fake_tts(text, output, voice):
                output.write_bytes(b"RIFF" + b"1" * 256)
                return [{"word": "x", "start": 0.0, "end": 1.0}]

            ffmpeg_inputs = []

            def fake_run(cmd, **kwargs):
                if "-i" in cmd:
                    ffmpeg_inputs.append(str(cmd[cmd.index("-i") + 1]))
                out = Path(cmd[-1])
                if out.suffix == ".mp3":
                    out.write_bytes(b"mp3" + b"2" * 256)
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("scripts.voice_engine.EdgeTTSProvider.synthesize_with_timing", side_effect=fake_tts), patch(
                "scripts.voice_engine.EdgeTTSProvider._get_duration", return_value=1.0
            ), patch("scripts.voice_engine.VoiceEngine._concat", return_value=fallback_audio), patch(
                "scripts.voice_engine.DeAIProcessor.apply", return_value=fallback_audio
            ), patch("scripts.voice_engine.subprocess.run", side_effect=fake_run):
                result = VoiceEngine(root).synthesize("hello.", lang="en", genre="tech", provider="edge")

            self.assertTrue(Path(result["audio"]).is_file())
            self.assertIn(str(fallback_audio), ffmpeg_inputs)


if __name__ == "__main__":
    unittest.main()
