from pathlib import Path

from PIL import Image

from content_platform.cover_director import build_cover_direction, render_cover_poster
from content_platform.cover_quality import validate_cover


def test_cover_direction_is_platform_specific_and_avoids_recent_style():
    recent = ["kuaishou:evidence_interface:cinematic_tech"]
    kuaishou = build_cover_direction(
        platform="kuaishou",
        topic="AI 工具工作流",
        title="别再来回切 AI 工具",
        body="展示接口、流程和最终验证结果。",
        recent_direction_ids=recent,
    )
    youtube = build_cover_direction(
        platform="youtube",
        topic="AI 工具工作流",
        title="Stop Switching AI Tools",
        body="Show the workflow and verified result.",
    )

    assert kuaishou["direction_id"] not in recent
    assert kuaishou["target_size"] == [1080, 1920]
    assert youtube["target_size"] == [1920, 1080]
    assert kuaishou["platform_profile"] != youtube["platform_profile"]
    assert kuaishou["background_prompt"].endswith("no text, no letters, no logo, no watermark")
    assert not youtube["subtitle_text"].endswith("with")


def test_rendered_cover_contains_typography_and_machine_evidence(tmp_path: Path):
    background = tmp_path / "background.jpg"
    Image.new("RGB", (1400, 1800), (18, 32, 52)).save(background)
    output = tmp_path / "cover.png"
    direction = build_cover_direction(
        platform="kuaishou",
        topic="AI 工作流",
        title="工具越多，效率越低？",
        body="一个入口串起文案、图片和语音。",
    )

    evidence = render_cover_poster(background, output, direction)

    assert output.is_file()
    assert Image.open(output).size == (1080, 1920)
    assert evidence["title_text"]
    assert evidence["typography_overlay_verified"] is True
    assert evidence["background_sha256"] != evidence["composite_sha256"]
    assert evidence["visual_variance_verified"] is True
    assert 1 <= evidence["title_line_count"] <= 3
    assert validate_cover(output, evidence, "kuaishou")["passed"] is True


def test_chinese_cover_subtitle_stops_at_a_complete_clause():
    direction = build_cover_direction(
        platform="kuaishou",
        topic="AI 工具工作流",
        title="别再到处攒 AI 工具",
        body="市面上AI工具多到数不清，写文案用一个，生图用一个，语音合成又一个。",
    )

    assert direction["subtitle_text"] == "市面上AI工具多到数不清，写文案用一个，生图用一个"
    assert not direction["subtitle_text"].endswith("语音")
