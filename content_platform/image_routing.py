"""Deterministic image intent routing shared by content workflows."""

from __future__ import annotations

import re
from pathlib import Path


_PLATFORM_DIMENSIONS = {
    "wechat": (1200, 800, "3:2"),
    "xiaohongshu": (1080, 1440, "3:4"),
    "douyin_ai": (1080, 1920, "9:16"),
    "douyin_pet": (1080, 1920, "9:16"),
    "kuaishou": (1080, 1920, "9:16"),
    "bilibili": (1920, 1080, "16:9"),
    "shipinhao": (1080, 1920, "9:16"),
    "zhihu": (1200, 800, "3:2"),
    "juejin": (1200, 800, "3:2"),
    "youtube": (1920, 1080, "16:9"),
    "tiktok": (1080, 1920, "9:16"),
    "twitter": (1600, 900, "16:9"),
}

_PLATFORM_ALIASES = {
    "douyin": "douyin_ai",
    "rednote": "xiaohongshu",
    "weixin": "wechat",
    "wechat_official": "wechat",
    "x": "twitter",
    "youtube_shorts": "youtube",
}

SUPPORTED_PLATFORMS = tuple(_PLATFORM_DIMENSIONS)
SUPPORTED_ROLES = ("cover", "section", "knowledge_card", "video_scene", "edit")

_REAL_SCENE_SIGNALS = (
    "animal",
    "city",
    "developer",
    "factory",
    "family",
    "food",
    "interview",
    "landscape",
    "nature",
    "office",
    "person",
    "pet",
    "physical product",
    "street",
    "team",
    "travel",
    "workspace",
    "人物",
    "办公室",
    "城市",
    "宠物",
    "工厂",
    "旅行",
    "现场",
    "真人",
    "美食",
    "自然",
    "采访",
)

_EDITORIAL_SIGNALS = (
    "abstract",
    "agent",
    "ai",
    "analysis",
    "api",
    "architecture",
    "automation",
    "checklist",
    "code",
    "concept",
    "data",
    "diagram",
    "framework",
    "llm",
    "metric",
    "process",
    "software",
    "strategy",
    "system",
    "workflow",
    "人工智能",
    "代码",
    "分析",
    "大模型",
    "工作流",
    "数据",
    "架构",
    "清单",
    "流程",
    "策略",
    "系统",
    "自动化",
)

_VISUAL_CONCEPT_GROUPS = (
    (("ai", "人工智能", "大模型", "hermes", "智能体", "agent"), "AI software agent"),
    (("工作流", "workflow", "自动化", "automation"), "connected workflow task nodes"),
    (("检索", "搜索", "自己找", "research", "search", "retrieval"), "information retrieval search"),
    (("内容管理", "自媒体", "content management"), "content management dashboard"),
    (("代码", "开发", "code", "developer"), "software development interface"),
    (("数据", "指标", "data", "metric"), "data analytics dashboard"),
    (("宠物", "猫", "狗", "pet", "cat", "dog"), "cat and dog"),
    (("每天", "重复", "反复", "循环", "repeat", "repetitive", "loop"), "repetitive task loop"),
    (("手动", "人工操作", "每天喂", "喂", "manual"), "human working"),
    (("手动喂饭", "喂ai", "feed ai", "manual feeding"), "human feeding computer"),
    (("记忆", "上下文", "memory", "context"), "organized memory archive"),
    (("我是谁", "身份", "profile", "identity"), "identity profile card"),
    (("时间", "耗时", "一个月", "deadline", "time cost"), "time cost clock calendar"),
)

_REAL_SCENE_TIEBREAK_PLATFORMS = {
    "douyin_pet",
    "kuaishou",
    "shipinhao",
    "tiktok",
    "xiaohongshu",
}


def route_image_request(
    *,
    platform: str,
    role: str,
    topic: str,
    section: str = "",
    input_image: str | Path | None = None,
) -> dict:
    """Compile a provider-neutral image request from platform and content intent."""
    normalized_platform = str(platform or "").casefold().strip()
    normalized_platform = _PLATFORM_ALIASES.get(normalized_platform, normalized_platform)
    normalized_role = str(role or "").casefold().strip().replace("-", "_")
    if normalized_platform not in _PLATFORM_DIMENSIONS:
        raise ValueError(f"unsupported image platform: {platform}")
    if normalized_role not in SUPPORTED_ROLES:
        raise ValueError(f"unsupported image role: {role}")
    if normalized_role == "edit" and not str(input_image or "").strip():
        raise ValueError("input_image is required for image edit requests")

    intent, semantic_required, provider_kinds = _role_route(
        normalized_platform,
        normalized_role,
        topic,
        section,
    )
    width, height, aspect_ratio = _PLATFORM_DIMENSIONS[normalized_platform]
    return {
        "platform": normalized_platform,
        "role": normalized_role,
        "intent": intent,
        "dimensions": [width, height],
        "aspect_ratio": aspect_ratio,
        "semantic_required": semantic_required,
        "preferred_provider_kinds": provider_kinds,
        "expected_concepts": _expected_concepts(topic, section),
    }


def _role_route(platform: str, role: str, topic: str, section: str) -> tuple[str, bool, list[str]]:
    if role == "cover":
        return "cinematic_cover", True, ["generated_image", "real_scene_search"]
    if role == "knowledge_card":
        return "knowledge_card_background", False, ["generated_image"]
    if role == "edit":
        return "image_edit", True, ["generated_image_and_edit"]
    if platform == "xiaohongshu" and role in {"section", "video_scene"}:
        return "real_scene", True, ["real_scene_search", "generated_image"]

    intent = _content_intent(platform, topic, section)
    if intent == "real_scene":
        return intent, True, ["real_scene_search", "generated_image"]
    return intent, True, ["generated_image", "real_scene_search"]


def _content_intent(platform: str, topic: str, section: str) -> str:
    text = f"{topic} {section}".casefold()
    real_score = sum(_contains_signal(text, signal) for signal in _REAL_SCENE_SIGNALS)
    editorial_score = sum(_contains_signal(text, signal) for signal in _EDITORIAL_SIGNALS)
    if real_score > editorial_score:
        return "real_scene"
    if editorial_score > real_score:
        return "editorial_illustration"
    if platform in _REAL_SCENE_TIEBREAK_PLATFORMS:
        return "real_scene"
    return "editorial_illustration"


def _contains_signal(text: str, signal: str) -> bool:
    if any(ord(character) > 127 for character in signal):
        return signal in text
    pattern = rf"(?<![a-z0-9]){re.escape(signal)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _expected_concepts(topic: str, section: str) -> list[str]:
    concepts: list[str] = []
    seen: set[str] = set()
    for value in (topic, section):
        concept = str(value or "").strip()
        key = concept.casefold()
        if concept and key not in seen:
            concepts.append(concept)
            seen.add(key)
    return concepts


def visual_concepts(text: str) -> list[str]:
    value = str(text or "").casefold()
    concepts = []
    for signals, concept in _VISUAL_CONCEPT_GROUPS:
        if any(_contains_signal(value, signal) for signal in signals):
            concepts.append(concept)
    return concepts[:4]


__all__ = ["SUPPORTED_PLATFORMS", "SUPPORTED_ROLES", "route_image_request", "visual_concepts"]
