from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[..., Any]
AudioProbe = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class HojoRuntimeConfig:
    home: Path
    timeout_seconds: float = 45.0

    @classmethod
    def from_env(cls) -> "HojoRuntimeConfig":
        home = Path(
            os.environ.get(
                "HOJO_TTS_HOME",
                str(Path.home() / ".local" / "share" / "hojo-tts-light-40m"),
            )
        )
        timeout = max(1.0, float(os.environ.get("HOJO_TTS_TIMEOUT_SECONDS", "45")))
        return cls(home=home, timeout_seconds=timeout)

    @property
    def python(self) -> Path:
        return self.home / ".venv" / "bin" / "python"

    @property
    def worker(self) -> Path:
        return self.home / "hojo_worker.py"

    @property
    def models(self) -> Path:
        return self.home / "models"

    @property
    def gate(self) -> Path:
        return self.home / "quality_gate.json"


_HOJO_VOICE_MAP = {
    "zh-CN-XiaoxiaoNeural": "hojo_zh_f_01",
    "zh-CN-XiaoyiNeural": "hojo_zh_f_02",
    "zh-TW-HsiaoYuNeural": "hojo_zh_f_02",
    # Hojo currently has no Chinese male voice. Use a Chinese voice rather than
    # silently sending Chinese narration through an English voice embedding.
    "zh-CN-YunyangNeural": "hojo_zh_f_01",
    "zh-CN-YunjianNeural": "hojo_zh_f_01",
    "zh-CN-YunxiNeural": "hojo_zh_f_02",
    "zh-CN-YunxiaNeural": "hojo_zh_f_02",
    "en-US-JennyNeural": "hojo_en_f_01",
    "en-US-AriaNeural": "hojo_en_f_02",
    "en-US-GuyNeural": "hojo_en_m_02",
    "en-US-EricNeural": "hojo_en_m_03",
    "en-GB-RyanNeural": "hojo_en_m_02",
}
_HOJO_DEFAULTS = {"zh": "hojo_zh_f_01", "en": "hojo_en_f_01"}
_EDGE_DEFAULTS = {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-JennyNeural"}


def probe_hojo(config: HojoRuntimeConfig | None = None) -> dict[str, Any]:
    config = config or HojoRuntimeConfig.from_env()
    failures: list[str] = []
    try:
        gate = json.loads(config.gate.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        gate = {}
    if gate.get("approved") is not True or gate.get("decision") != "hojo-first":
        failures.append("hojo_quality_gate_not_approved")
    if os.environ.get("HOJO_TTS_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        failures.append("hojo_disabled")
    required = (
        config.python,
        config.worker,
        config.models / "Hojo-TTS-Light-40M-llm.onnx",
    )
    if any(not path.is_file() for path in required):
        failures.append("hojo_installation_incomplete")
    return {
        "available": not failures,
        "failures": failures,
        "model": "HojoAI/Hojo-TTS-Light-40M",
        "quality_decision": str(gate.get("decision") or ""),
    }


def resolve_hojo_voice(language: str, requested_voice: str | None) -> str:
    language = str(language or "").lower()
    mapped = _HOJO_VOICE_MAP.get(str(requested_voice or ""))
    if mapped and mapped.startswith(f"hojo_{language}_"):
        return mapped
    return _HOJO_DEFAULTS.get(language, "")


def provider_chain(
    requested_provider: str | None,
    *,
    language: str,
    config: HojoRuntimeConfig | None = None,
) -> list[str]:
    requested = str(requested_provider or "auto").strip().lower().replace("_", "-")
    hojo_available = probe_hojo(config).get("available") is True and language in _HOJO_DEFAULTS
    if requested in {"edge", "edge-tts"}:
        return ["edge"]
    if requested == "qwen":
        return []
    if requested in {"hojo", "hojo-first", "auto"} and hojo_available:
        return ["hojo", "edge"]
    return ["edge"]


def _probe_audio(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,sample_rate,channels:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        payload = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
        stream = next((row for row in payload.get("streams") or [] if row.get("codec_name")), {})
        duration = float((payload.get("format") or {}).get("duration") or 0)
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        duration, sample_rate, channels, stream = 0.0, 0, 0, {}
    passed = path.is_file() and path.stat().st_size >= 1000 and duration > 0 and sample_rate > 0 and channels > 0
    return {
        "passed": passed,
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "codec_name": str(stream.get("codec_name") or ""),
    }


def _partial_path(output: Path, suffix: str) -> Path:
    return output.parent / f".{output.stem}.partial-{uuid.uuid4().hex}{suffix}"


def synthesize_tts_segment(
    text: str,
    output: str | Path,
    *,
    language: str,
    voice: str | None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    requested_provider: str = "auto",
    config: HojoRuntimeConfig | None = None,
    command_runner: CommandRunner = subprocess.run,
    audio_probe: AudioProbe = _probe_audio,
) -> dict[str, Any]:
    if not str(text or "").strip():
        raise ValueError("tts_text_empty")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = config or HojoRuntimeConfig.from_env()
    attempts: list[dict[str, Any]] = []
    chain = provider_chain(requested_provider, language=language, config=config)

    for provider in chain:
        started = time.perf_counter()
        candidate = _partial_path(output, output.suffix or ".wav")
        worker_wav = _partial_path(output, ".wav")
        edge_source: Path | None = None
        try:
            if provider == "hojo":
                actual_voice = resolve_hojo_voice(language, voice)
                if not actual_voice:
                    raise RuntimeError("hojo_language_or_voice_unsupported")
                result = command_runner(
                    [
                        str(config.python),
                        str(config.worker),
                        "--models",
                        str(config.models),
                        "--text",
                        text,
                        "--voice",
                        actual_voice,
                        "--output",
                        str(worker_wav),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds,
                    check=False,
                )
                if result.returncode != 0 or not worker_wav.is_file():
                    raise RuntimeError(f"hojo_failed:{str(result.stderr or '')[-240:]}")
                codec = ["-codec:a", "pcm_s16le"] if output.suffix.lower() == ".wav" else ["-codec:a", "libmp3lame", "-q:a", "2"]
                converted = command_runner(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(worker_wav),
                        *codec,
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        str(candidate),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if converted.returncode != 0 or not candidate.is_file():
                    raise RuntimeError(f"hojo_format_convert_failed:{str(converted.stderr or '')[-240:]}")
            else:
                actual_voice = voice if str(voice or "").startswith(("zh-", "en-")) else _EDGE_DEFAULTS.get(language, _EDGE_DEFAULTS["en"])
                edge_source = _partial_path(output, ".edge.mp3")
                result = command_runner(
                    [
                        "edge-tts",
                        "--voice",
                        actual_voice,
                        "--rate",
                        rate,
                        "--pitch",
                        pitch,
                        "--text",
                        text,
                        "--write-media",
                        str(edge_source),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode != 0 or not edge_source.is_file():
                    raise RuntimeError(f"edge_tts_failed:{str(result.stderr or '')[-240:]}")
                codec = ["-codec:a", "pcm_s16le"] if output.suffix.lower() == ".wav" else ["-codec:a", "libmp3lame", "-q:a", "2"]
                converted = command_runner(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(edge_source), *codec, "-ar", "44100", "-ac", "2", str(candidate)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                edge_source.unlink(missing_ok=True)
                if converted.returncode != 0 or not candidate.is_file():
                    raise RuntimeError(f"edge_tts_format_convert_failed:{str(converted.stderr or '')[-240:]}")

            evidence = audio_probe(candidate)
            if evidence.get("passed") is not True or int(evidence.get("sample_rate") or 0) != 44100 or int(evidence.get("channels") or 0) != 2:
                raise RuntimeError("tts_audio_probe_failed")
            os.replace(candidate, output)
            worker_wav.unlink(missing_ok=True)
            elapsed = round(time.perf_counter() - started, 3)
            attempts.append({"provider": provider, "status": "succeeded", "elapsed_seconds": elapsed})
            return {
                "provider": "hojo" if provider == "hojo" else "edge-tts",
                "requested_provider": requested_provider,
                "model": "HojoAI/Hojo-TTS-Light-40M" if provider == "hojo" else "edge-tts",
                "voice": actual_voice,
                "requested_voice": str(voice or ""),
                "voice_substituted": bool(voice and actual_voice != voice),
                "rate": rate,
                "pitch": pitch,
                "fallback_used": len(attempts) > 1,
                "attempts": attempts,
                "elapsed_seconds": elapsed,
                "audio": {**evidence, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()},
            }
        except Exception as exc:
            attempts.append(
                {
                    "provider": provider,
                    "status": "failed",
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "reason": str(exc)[:300],
                }
            )
            candidate.unlink(missing_ok=True)
            worker_wav.unlink(missing_ok=True)
            if edge_source is not None:
                edge_source.unlink(missing_ok=True)

    raise RuntimeError(f"tts_all_providers_failed:{json.dumps(attempts, ensure_ascii=False)}")
