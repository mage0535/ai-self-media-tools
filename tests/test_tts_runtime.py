import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from content_platform.tts_runtime import (
    HojoRuntimeConfig,
    provider_chain,
    resolve_hojo_voice,
    synthesize_tts_segment,
)


def _install_hojo(root: Path, *, approved: bool = True, decision: str = "hojo-first") -> HojoRuntimeConfig:
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("python", encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "Hojo-TTS-Light-40M-llm.onnx").write_bytes(b"model")
    (root / "hojo_worker.py").write_text("worker", encoding="utf-8")
    (root / "quality_gate.json").write_text(
        json.dumps({"approved": approved, "decision": decision}), encoding="utf-8"
    )
    return HojoRuntimeConfig(home=root, timeout_seconds=5)


def _valid_probe(path: Path) -> dict:
    return {
        "passed": path.is_file() and path.stat().st_size > 0,
        "duration_seconds": 1.25,
        "sample_rate": 44100,
        "channels": 2,
        "codec_name": "pcm_s16le",
    }


def test_auto_uses_hojo_only_when_durable_quality_gate_and_installation_pass(tmp_path: Path):
    config = _install_hojo(tmp_path / "hojo")
    assert provider_chain("auto", language="zh", config=config) == ["hojo", "edge"]

    (config.home / "quality_gate.json").write_text(
        json.dumps({"approved": True, "decision": "edge-first"}), encoding="utf-8"
    )
    assert provider_chain("auto", language="zh", config=config) == ["edge"]


def test_chinese_edge_voice_never_maps_to_an_english_hojo_voice():
    assert resolve_hojo_voice("zh", "zh-CN-YunjianNeural") == "hojo_zh_f_01"
    assert resolve_hojo_voice("zh", "zh-CN-XiaoyiNeural") == "hojo_zh_f_02"
    assert resolve_hojo_voice("en", "en-US-GuyNeural") == "hojo_en_m_02"


def test_hojo_success_is_atomic_and_records_actual_provider(tmp_path: Path):
    config = _install_hojo(tmp_path / "hojo")
    output = tmp_path / "voice.mp3"

    def fake_run(command, **_kwargs):
        target = Path(command[-1])
        target.write_bytes(b"audio" * 400)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    result = synthesize_tts_segment(
        "人工智能工具。",
        output,
        language="zh",
        voice="zh-CN-YunjianNeural",
        requested_provider="auto",
        config=config,
        command_runner=fake_run,
        audio_probe=_valid_probe,
    )

    assert output.read_bytes().startswith(b"audio")
    assert result["provider"] == "hojo"
    assert result["requested_provider"] == "auto"
    assert result["voice"] == "hojo_zh_f_01"
    assert result["fallback_used"] is False
    assert result["audio"]["passed"] is True
    assert not list(tmp_path.glob("*.partial*"))


def test_invalid_hojo_output_falls_back_to_edge_with_failure_evidence(tmp_path: Path):
    config = _install_hojo(tmp_path / "hojo")
    output = tmp_path / "voice.mp3"

    def fake_run(command, **_kwargs):
        if "hojo_worker.py" in " ".join(map(str, command)):
            return SimpleNamespace(returncode=1, stdout="", stderr="onnx failed")
        target = Path(command[-1])
        target.write_bytes(b"edge" * 400)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = synthesize_tts_segment(
        "人工智能工具。",
        output,
        language="zh",
        voice="zh-CN-XiaoxiaoNeural",
        requested_provider="auto",
        config=config,
        command_runner=fake_run,
        audio_probe=_valid_probe,
    )

    assert result["provider"] == "edge-tts"
    assert result["fallback_used"] is True
    assert result["attempts"][0]["provider"] == "hojo"
    assert result["attempts"][0]["status"] == "failed"
    assert result["attempts"][1]["status"] == "succeeded"


def test_all_provider_failures_preserve_existing_output(tmp_path: Path):
    config = _install_hojo(tmp_path / "hojo")
    output = tmp_path / "voice.mp3"
    output.write_bytes(b"previous-valid-audio")

    def always_fail(_command, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="failed")

    with pytest.raises(RuntimeError, match="tts_all_providers_failed"):
        synthesize_tts_segment(
            "人工智能工具。",
            output,
            language="zh",
            voice="zh-CN-XiaoxiaoNeural",
            requested_provider="auto",
            config=config,
            command_runner=always_fail,
            audio_probe=_valid_probe,
        )

    assert output.read_bytes() == b"previous-valid-audio"


def test_qwen_is_not_silently_executed_as_edge_by_the_hojo_edge_runtime(tmp_path: Path):
    config = _install_hojo(tmp_path / "hojo")
    calls = []

    with pytest.raises(RuntimeError, match="tts_all_providers_failed"):
        synthesize_tts_segment(
            "explicit provider",
            tmp_path / "voice.mp3",
            language="en",
            voice="en-US-GuyNeural",
            requested_provider="qwen",
            config=config,
            command_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            audio_probe=_valid_probe,
        )

    assert calls == []
