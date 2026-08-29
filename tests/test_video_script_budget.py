import json

from content_platform.media import MediaBridge
from scripts.film_renderer import validate_render_durations
from pathlib import Path
from unittest.mock import patch


def test_video_script_compiler_converts_long_article_to_eight_bounded_beats(tmp_path):
    body = "\n\n".join(
        f"第{i}个要点说明了一个可执行的 AI 视频工作流步骤，并给出避免常见错误的具体方法和检查依据。"
        for i in range(1, 14)
    )
    result = MediaBridge.compile_video_script({"title": "五分钟做出 AI 视频", "body": body})

    assert result["source"] == "derived_from_draft"
    assert len(result["segments"]) == 8
    assert all(8 <= len(segment) <= 40 for segment in result["segments"])
    assert result["input_characters"] == len(body)
    assert result["output_characters"] < result["input_characters"]
    assert result["script"] == "\n\n".join(result["segments"])


def test_video_script_compiler_normalizes_an_oversized_explicit_script():
    explicit = "\n\n".join(f"第{i}段内容" * 20 for i in range(1, 10))
    result = MediaBridge.compile_video_script({"draft_meta": {"video_script": explicit}})

    assert result["source"] == "normalized_explicit_script"
    assert len(result["segments"]) == 8
    assert all(len(segment) <= 40 for segment in result["segments"])


def test_video_script_compiler_preserves_english_word_budget():
    body = " ".join(f"word{index}" for index in range(140))

    result = MediaBridge.compile_video_script({"body": body})

    assert len(result["segments"]) == 6
    assert sum(len(segment.split()) for segment in result["segments"]) == 140
    assert all(len(segment.split()) <= 24 for segment in result["segments"])
    assert result["max_words_per_segment"] == 24


def test_film_renderer_rejects_runaway_tts_durations_before_rendering():
    assert validate_render_durations([4.0] * 8)["passed"] is True

    result = validate_render_durations([4.0] * 7 + [265.0])
    assert result["passed"] is False
    assert "segment_duration_exceeded" in result["failures"]


def test_video_bridge_passes_compiled_narration_and_persists_its_contract(tmp_path):
    script = tmp_path / "video_provider.py"
    script.write_text("# fixture", encoding="utf-8")
    body = "\n\n".join(f"第{i}段讲一个可执行步骤，并说明验证结果和避免错误的方法。" for i in range(1, 12))
    bridge = MediaBridge({"video": {"enabled": True, "script": str(script)}}, tmp_path)

    def fake_run(command, **kwargs):
        output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "generated.mp4").write_bytes(b"video")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run) as run:
        artifact = bridge.generate("video", {"id": "video-budget", "topic": "Topic", "body": body})

    narration = run.call_args.args[0][-2]
    contract = Path(artifact["path"]).parent / "video_script_manifest.json"
    saved_contract = json.loads(contract.read_text(encoding="utf-8"))
    assert len(narration) < len(body)
    assert narration == saved_contract["script"]
    assert saved_contract["source"] == "derived_from_draft"
