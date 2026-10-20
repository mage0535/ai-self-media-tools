import json
from pathlib import Path

from content_platform.intelligence import build_generation_context, collect_reference_posts
from content_platform.media_quality import validate_platform_article_packet
from content_platform.media_source_router import plan_source_route
from content_platform.prompt_compiler import compile_prompt_bundle
from content_platform.source_registry import SOURCES, validate_source_evidence


def test_structured_trend_evidence_enters_generation_context():
    brief = {"platforms": ["zhihu"], "trend_evidence": {"source": "zhihu_hot", "samples": [{"title": "AI 工作流", "body": "先看证据再自动化", "url": "https://example.test/a"}]}}
    posts = collect_reference_posts(brief)
    assert len(posts) == 1
    assert build_generation_context("AI 工作流", brief)["style"]["sample_count"] == 1


def test_zhihu_english_placeholder_and_unavailable_evidence_fail_closed():
    packet = {
        "platform": "zhihu", "language": "zh", "title": "AI 工作流实践指南",
        "body": "Execution guide placeholder body. Source status: unavailable.",
        "source_status": "unavailable", "section_image_map": [],
    }
    result = validate_platform_article_packet(packet, "zhihu")
    assert not result["gates"]["language_fail_closed"]["passed"]
    assert not result["gates"]["evidence_fail_closed"]["passed"]


def test_runtime_sources_route_and_missing_evidence_blocks():
    runtime = [name for name, profile in SOURCES.items() if profile.get("status") == "runtime_ready"]
    assert runtime
    for name in runtime:
        assert validate_source_evidence(name, {})["passed"] is False
    image_sources = {row["source"] for row in plan_source_route("image", content_form="cover", free_only=True)}
    assert {"pexels", "pixabay"}.issubset(image_sources)
    assert not {"wikimedia", "playwright_mcp", "apify_mcp"}.intersection(image_sources)


def test_prompt_registry_supports_youtube_variants_without_fixed_ratio():
    neutral = compile_prompt_bundle({"platform": "youtube", "content_type": "video", "topic": "x", "audience": "y", "goal": "z", "evidence": ["url"], "constraints": ["c"]})
    long_form = compile_prompt_bundle({"platform": "youtube", "content_type": "long_video", "topic": "x", "audience": "y", "goal": "z", "evidence": ["url"], "constraints": ["c"]})
    shorts = compile_prompt_bundle({"platform": "youtube", "content_type": "short_video", "topic": "x", "audience": "y", "goal": "z", "evidence": ["url"], "constraints": ["c"]})
    assert neutral["quality_contract"]["aspect_ratio"] is None
    assert long_form["quality_contract"]["aspect_ratio"] == "16:9"
    assert shorts["quality_contract"]["aspect_ratio"] == "9:16"


def test_registry_declares_expected_statuses_and_forms():
    registry = json.loads(Path("config/creative_capability_registry.json").read_text(encoding="utf-8"))
    rows = {row["source"].casefold(): row for row in registry["capabilities"] if row.get("source")}
    for source in ("pexels", "pixabay"):
        row = rows[source]
        assert row["availability"] == "runtime_ready"
        assert {"article", "cover", "inline_image", "short_video", "long_video"}.issubset(row["applies_to"])
    assert not any(row.get("source") in {"Wikimedia Commons", "Playwright MCP", "Apify MCP"} and row.get("availability") == "runtime_ready" for row in registry["capabilities"])
