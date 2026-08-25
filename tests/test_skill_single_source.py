from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_platform.generation_context_compiler import compile_generation_context
from content_platform.platform_workflow_context import GENERIC_SKILLS, PLATFORM_SKILLS
from content_platform import preflight_manifest
from content_platform.skill_rule_compiler import compile_skill_rules, default_skill_paths


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("platform", "expected_source"),
    [
        ("kuaishou", "skill:content/kuaishou-publishing-workflow"),
        ("tiktok", "skill:content/intl-short-video-pipeline"),
        ("youtube", "skill:content/intl-short-video-pipeline"),
        ("bilibili", "skill:content/channel-operations-workflow"),
        ("shipinhao", "skill:content/kuaishou-content-publishing"),
        ("xiaohongshu", "skill:content/xiaohongshu-content-enhancer"),
        ("rednote", "skill:content/xiaohongshu-content-enhancer"),
        ("wechat", "skill:wechat-pipeline-v2"),
        ("zhihu", "skill:content/zhihu-publishing-workflow"),
        ("juejin", "skill:content/juejin-publishing-workflow"),
        ("douyin", "skill:douyin-repost-workflow"),
        ("douyin_ai", "skill:douyin-daily-analysis-workflow"),
        ("douyin_pet", "skill:douyin-repost-workflow"),
        ("x", "skill:social-media/x-twitter-autopublish"),
        ("twitter", "skill:social-media/x-twitter-autopublish"),
    ],
)
def test_all_platform_skill_rules_reach_bounded_generation_context(platform: str, expected_source: str) -> None:
    paths = default_skill_paths(platform, root=ROOT)
    compiled = compile_skill_rules(paths, root=ROOT)

    bounded = compile_generation_context(
        platform=platform,
        content_format="article",
        stage="generate",
        brief={"compiled_skill_rules": compiled},
    )
    payload = json.loads(bounded["text"])

    assert expected_source in {item["source"] for item in payload["selected_rule_ids"]}
    assert bounded["byte_count"] <= 12_000


@pytest.mark.parametrize("platform", ["wechat", "kuaishou", "douyin_ai", "shipinhao", "rednote", "x"])
def test_platform_workflow_skill_exports_are_derived_from_canonical_requirements(platform: str) -> None:
    exported = set(GENERIC_SKILLS + PLATFORM_SKILLS.get(platform, []))

    required_workflow_skills = getattr(preflight_manifest, "required_workflow_skills", None)

    assert required_workflow_skills is not None, "canonical workflow-skill derivation is missing"
    assert exported == set(required_workflow_skills(platform))
