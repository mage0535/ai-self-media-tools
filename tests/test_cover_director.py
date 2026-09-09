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
    assert evidence["horizontal_safe_zone_verified"] is True
    assert evidence["max_text_line_width_px"] <= evidence["text_safe_width_px"]
    assert validate_cover(output, evidence, "kuaishou")["passed"] is True


def test_long_mixed_title_is_pixel_wrapped_inside_horizontal_safe_zone(tmp_path: Path):
    background = tmp_path / "background.jpg"
    Image.new("RGB", (1200, 2133), (24, 36, 48)).save(background)
    output = tmp_path / "cover.png"
    direction = build_cover_direction(
        platform="kuaishou", topic="AI 工具工作流",
        title="AI能力一次配齐，别再到处攒工具",
        body="写文案开一个网页，生图切另一个，配音再换一个。",
    )

    evidence = render_cover_poster(background, output, direction)

    assert evidence["horizontal_safe_zone_verified"] is True
    assert evidence["max_text_line_width_px"] <= evidence["text_safe_width_px"]
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


def test_three_step_tool_reduction_cover_uses_complete_payoff_subtitle():
    direction = build_cover_direction(
        platform="kuaishou",
        topic="AI工具越装越多，效率反而下降",
        title="AI工具越装越多，效率反而下降？三步精简回来",
        body="第一步只留高频工具。第二步合并重复功能。第三步固定工具分工。",
    )

    assert direction["subtitle_text"] == "只留主力入口，固定分工和流程"


def test_youtube_cover_keeps_complete_question_and_skips_question_subtitle():
    direction = build_cover_direction(
        platform="youtube", topic="AI agents",
        title="Still Think ChatGPT Is an AI Agent? Here's What You're Missing",
        body="Why does this distinction matter? A chatbot replies once, but an agent plans and acts.",
    )

    assert direction["title_text"] == "Still Think ChatGPT Is an AI Agent"
    assert direction["subtitle_text"] == "Chatbots reply. Agents plan, act, and verify."


def test_agent_skills_cover_uses_workflow_playbook_visual_and_clean_subtitle():
    direction = build_cover_direction(
        platform="juejin",
        topic="Agent Skills 傻瓜式教程",
        title="别再重复写 Prompt 了",
        body=(
            "## 一个被严重低估的技术标准\n\n"
            "Agent Skills 把重复工作流封装成可复用的操作手册，执行后还要验证结果。"
        ),
    )

    assert direction["subtitle_text"] == "Agent Skills 把重复工作流封装成可复用的操作手册"
    assert "#" not in direction["subtitle_text"]
    assert "modular AI workflow playbook" in direction["background_prompt"]
    assert "connected skill cards" in direction["background_prompt"]
    assert "no generic humanoid robot" in direction["background_prompt"]
    assert "no generic portrait" in direction["background_prompt"]
    assert any("workflow playbook" in item for item in direction["focal_subjects"])
    assert direction["semantic_concepts"] == [
        "connected workflow task nodes",
        "step-by-step operating playbook",
    ]
