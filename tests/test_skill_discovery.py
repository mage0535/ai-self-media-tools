from pathlib import Path

from content_platform.skill_rule_compiler import discover_relevant_skill_paths
from content_platform.skill_rule_compiler import select_platform_rules


def _skill(root: Path, name: str, description: str) -> Path:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n", encoding="utf-8")
    return path


def test_video_skill_discovery_scans_all_and_selects_relevant_capabilities(tmp_path: Path):
    voice = _skill(tmp_path, "voice-engine", "TTS voice narration for video")
    cinema = _skill(tmp_path, "cinema-motion", "cinematic shots motion transitions and BGM")
    unrelated = _skill(tmp_path, "finance-ledger", "stock accounting and tax records")

    selected, report = discover_relevant_skill_paths(
        "kuaishou",
        {"content_format": "vertical_video", "content_domain": "tech", "visual_treatment": "cinematic"},
        root=tmp_path,
        hermes_root=tmp_path / "missing-hermes",
    )

    assert voice.resolve() in selected
    assert cinema.resolve() in selected
    assert unrelated.resolve() not in selected
    assert report["discovered_count"] == 3
    assert report["blocked_count"] == 1
    assert report["considered_count"] == 2
    assert report["selected_count"] == 2
    assert report["excluded_count"] == 0


def test_article_skill_discovery_selects_layout_image_and_seo(tmp_path: Path):
    article = _skill(tmp_path, "article-layout", "article image card layout cover SEO")
    video = _skill(tmp_path, "voice-only", "voice TTS audio")

    selected, _report = discover_relevant_skill_paths(
        "juejin",
        {"content_format": "article", "content_domain": "tech", "visual_treatment": "editorial"},
        root=tmp_path,
        hermes_root=tmp_path / "missing-hermes",
    )

    assert article.resolve() in selected
    assert video.resolve() not in selected


def test_shared_skill_rules_do_not_leak_other_platform_instructions():
    rules = [
        {"id": "shared:1", "source": "skill:content/channel-operations-workflow", "text": "douyin_pet 只允许猫狗治愈内容"},
        {"id": "shared:2", "source": "skill:content/channel-operations-workflow", "text": "快手发布后检查管理页定时时间"},
        {"id": "shared:3", "source": "skill:content/channel-operations-workflow", "text": "所有短视频必须有字幕"},
    ]

    selected = select_platform_rules(rules, "kuaishou")

    assert {row["id"] for row in selected} == {"shared:2", "shared:3"}


def test_video_skill_discovery_excludes_retired_and_format_conflicting_skills(tmp_path: Path):
    valid = _skill(tmp_path, "cinema-motion", "cinematic shots motion transitions and BGM")
    retired = _skill(tmp_path, "content-ai-autoclip", "Downloads and recompiles source videos")
    superseded = _skill(tmp_path, "kuaishou-video-publishing", "This skill is superseded by kuaishou-content-publishing")
    longform = _skill(tmp_path, "chinese-longform-content-standards", "Chinese longform article writing standards")

    selected, report = discover_relevant_skill_paths(
        "kuaishou",
        {"content_format": "vertical_video", "content_domain": "tech", "visual_treatment": "cinematic"},
        root=tmp_path,
        hermes_root=tmp_path / "missing-hermes",
    )

    assert valid.resolve() in selected
    assert retired.resolve() not in selected
    assert superseded.resolve() not in selected
    assert longform.resolve() not in selected
    assert report["retired_or_incompatible_count"] == 3
