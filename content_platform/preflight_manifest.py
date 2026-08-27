"""Pre-generation evidence manifest for channel content workflows.

The manifest is intentionally small and portable.  It proves that a content
packet was generated from the current rulebook, channel strategy, relevant
skills, visual policy, asset requirements, quality gates, and publish
constraints before media generation or delivery is attempted.
"""

from __future__ import annotations

from typing import Any


CURRENT_PREFLIGHT_MANIFEST_VERSION = "content_preflight_manifest_v2"

COMMON_REQUIRED_KEYS = [
    "version",
    "channel",
    "content_type",
    "rulebook",
    "strategy",
    "skills_loaded",
    "visual_policy",
    "topic_plan",
    "asset_requirements",
    "quality_gates",
    "publish_constraints",
    "run_contract",
]

_PREFLIGHT_BASE_SKILLS = {"meta/content-preflight", "content/content-strategy-workflow"}
_WORKFLOW_BASE_SKILLS = {
    "content/channel-operations-workflow",
    "content/visual-quality-standards",
    "content/content-copywriting-style",
}
_KNOWLEDGE_CARD_SKILL = {"content/knowledge-card-designer"}
_ARTICLE_SKILLS = {"content/content-seo-toolset", "content/content-open-notebook"}
_VIDEO_SKILLS = {"content/content-voice-engine"}
_AI_RESEARCH_SKILLS = {"content/content-github-star-explorer"}
_PREFLIGHT_ONLY_SKILLS = _PREFLIGHT_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | {
    "content/wechat-operational-strategy",
    "content/wechat-full-workflow",
    "wewrite",
    "no-ai-slop",
}

# This is the only hand-maintained channel-to-skill mapping. Runtime consumers
# derive their file-backed subset through required_workflow_skills().
REQUIRED_SKILLS_BY_CHANNEL = {
    "wechat": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _ARTICLE_SKILLS | {"content/wechat-operational-strategy", "content/wechat-full-workflow", "wechat-pipeline-v2", "wewrite", "no-ai-slop"},
    "weixin": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _ARTICLE_SKILLS | {"content/wechat-operational-strategy", "content/wechat-full-workflow", "wechat-pipeline-v2", "wewrite", "no-ai-slop"},
    "wechat_official": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _ARTICLE_SKILLS | {"content/wechat-operational-strategy", "content/wechat-full-workflow", "wechat-pipeline-v2", "wewrite", "no-ai-slop"},
    "kuaishou": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS | {"content/kuaishou-content-publishing", "content/kuaishou-publishing-workflow"},
    "douyin": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS | {"douyin-repost-workflow"},
    "douyin_ai": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS | _AI_RESEARCH_SKILLS | {"douyin-daily-analysis-workflow"},
    "douyin_pet": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS | {"douyin-repost-workflow"},
    "shipinhao": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS,
    "bilibili": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _VIDEO_SKILLS,
    "xiaohongshu": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | {"content/xiaohongshu-content-enhancer"},
    "rednote": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | {"content/xiaohongshu-content-enhancer"},
    "juejin": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _ARTICLE_SKILLS | _AI_RESEARCH_SKILLS | {"content/juejin-publishing-workflow"},
    "zhihu": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _KNOWLEDGE_CARD_SKILL | _ARTICLE_SKILLS | {"content/zhihu-publishing-workflow"},
    "tiktok": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _VIDEO_SKILLS | {"content/intl-short-video-pipeline"},
    "youtube": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | _VIDEO_SKILLS | {"content/intl-short-video-pipeline"},
    "x": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | {"social-media/x-twitter-autopublish"},
    "twitter": _PREFLIGHT_BASE_SKILLS | _WORKFLOW_BASE_SKILLS | {"social-media/x-twitter-autopublish"},
}


def required_skills_for_channel(channel: str) -> set[str]:
    """Return a copy of the canonical requirements for a normalized channel."""
    return set(REQUIRED_SKILLS_BY_CHANNEL.get(str(channel or "").casefold(), _PREFLIGHT_BASE_SKILLS))


def required_workflow_skills(channel: str) -> list[str]:
    """Return deterministic file-backed workflow skills derived from the canonical map."""
    return sorted(required_skills_for_channel(channel) - _PREFLIGHT_ONLY_SKILLS)

KNOWLEDGE_CARD_CONTENT_HINTS = {"knowledge_card", "card", "infographic", "image_card"}


def manifest_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Return the embedded preflight manifest, accepting legacy aliases."""
    manifest = packet.get("preflight_manifest") or packet.get("content_preflight_manifest") or {}
    return manifest if isinstance(manifest, dict) else {}


def build_preflight_manifest(
    *,
    channel: str,
    content_type: str,
    strategy_source: str,
    strategy_result_path: str,
    strategy_summary: str,
    selected_topic: str,
    selection_reason: str,
    content_angle: str,
    required_assets: list[str] | None = None,
    source_policy: str = "licensed_or_verified_runtime_assets",
    quality_gates: list[str] | None = None,
    delivery_health_required: bool = True,
    postcheck_required: bool = True,
    extra_skills: list[str] | None = None,
) -> dict[str, Any]:
    """Build the canonical manifest that generators should attach to packets."""
    normalized_channel = str(channel or "").casefold()
    skills = sorted(
        required_skills_for_channel(normalized_channel)
        | set(extra_skills or [])
    )
    from .run_contract import build_run_contract

    return {
        "version": CURRENT_PREFLIGHT_MANIFEST_VERSION,
        "channel": normalized_channel,
        "content_type": content_type,
        "rulebook": {
            "loaded": True,
            "path": "config/channel_content_rulebook.json",
            "channel_rules_loaded": True,
        },
        "strategy": {
            "source": strategy_source,
            "result_path": strategy_result_path,
            "summary": strategy_summary,
        },
        "skills_loaded": skills,
        "visual_policy": {
            "loaded": True,
            "policy_id": "visual_content_design_policy_v1",
        },
        "topic_plan": {
            "selected_topic": selected_topic,
            "selection_reason": selection_reason,
            "content_angle": content_angle,
        },
        "asset_requirements": {
            "required_assets": list(required_assets or []),
            "source_policy": source_policy,
        },
        "quality_gates": list(quality_gates or ["content_quality", "visual_quality", "asset_license", "delivery_postcheck"]),
        "publish_constraints": {
            "delivery_health_required": bool(delivery_health_required),
            "postcheck_required": bool(postcheck_required),
        },
        "run_contract": build_run_contract(normalized_channel),
    }


def infer_preflight_manifest(packet: dict[str, Any], channel: str | None = None) -> dict[str, Any]:
    """Build a manifest from existing packet evidence, or return {}.

    This is used by Pipeline as a safe auto-integration step.  It does not
    invent missing operations evidence; callers with incomplete packets still
    fail the normal preflight gate.
    """
    existing_manifest = manifest_from_packet(packet)
    if existing_manifest and all(_present(existing_manifest.get(key)) for key in COMMON_REQUIRED_KEYS):
        return existing_manifest

    normalized_channel = str(channel or packet.get("platform") or "").casefold()
    evidence = _dict_value(packet, "preflight_evidence", "workflow_evidence")
    strategy = _dict_value(packet, "strategy_brief", "strategy")
    topic = _dict_value(packet, "topic_selection", "topic_plan")
    assets = _dict_value(packet, "asset_requirements", "preflight_asset_requirements")

    strategy_source = _first_text(
        evidence.get("strategy_source"),
        evidence.get("source"),
        strategy.get("source"),
        strategy.get("strategy_source"),
    )
    strategy_result_path = _first_text(
        evidence.get("strategy_result_path"),
        evidence.get("result_path"),
        strategy.get("strategy_result_path"),
        strategy.get("result_path"),
        packet.get("strategy_artifact"),
    )
    strategy_summary = _first_text(
        evidence.get("strategy_summary"),
        evidence.get("summary"),
        strategy.get("strategy_summary"),
        strategy.get("summary"),
    )
    selected_topic = _first_text(topic.get("selected_topic"), topic.get("topic"), strategy.get("selected_topic"))
    selection_reason = _first_text(topic.get("selection_reason"), topic.get("reason"), strategy.get("selection_reason"))
    content_angle = _first_text(topic.get("content_angle"), topic.get("article_angle"), strategy.get("content_angle"))
    content_type = _first_text(
        packet.get("content_type"),
        packet.get("content_form"),
        strategy.get("content_type"),
        strategy.get("content_form"),
        evidence.get("content_type"),
        existing_manifest.get("content_type"),
    )
    required_assets = assets.get("required_assets") if isinstance(assets.get("required_assets"), list) else []
    source_policy = _first_text(assets.get("source_policy"), packet.get("asset_source_policy"), "licensed_or_verified_runtime_assets")

    if not all(
        [
            normalized_channel,
            content_type,
            strategy_source,
            strategy_result_path,
            strategy_summary,
            selected_topic,
            selection_reason,
            content_angle,
            required_assets,
        ]
    ):
        return {}

    extra_skills = []
    if normalized_channel in ("wechat", "weixin", "wechat_official"):
        extra_skills.append("wewrite")
        extra_skills.append("no-ai-slop")
    if _content_uses_knowledge_cards(packet, {"content_type": content_type}):
        extra_skills.append("content/knowledge-card-designer")
    if _content_uses_visual_media(packet, {"content_type": content_type}):
        extra_skills.append("content/visual-quality-standards")

    return build_preflight_manifest(
        channel=normalized_channel,
        content_type=content_type,
        strategy_source=strategy_source,
        strategy_result_path=strategy_result_path,
        strategy_summary=strategy_summary,
        selected_topic=selected_topic,
        selection_reason=selection_reason,
        content_angle=content_angle,
        required_assets=[str(item) for item in required_assets],
        source_policy=source_policy,
        quality_gates=[str(item) for item in (packet.get("preflight_quality_gates") or [])] or None,
        extra_skills=extra_skills,
    )


def validate_preflight_manifest(packet: dict[str, Any], channel: str | None = None) -> dict[str, Any]:
    """Validate that a packet carries machine-checkable pre-generation evidence."""
    manifest = manifest_from_packet(packet)
    normalized_channel = str(channel or packet.get("platform") or manifest.get("channel") or "").casefold()
    failures: list[str] = []

    if not manifest:
        return _result(["preflight_manifest_missing"])

    for key in COMMON_REQUIRED_KEYS:
        if not _present(manifest.get(key)):
            failures.append(f"preflight_manifest.{key}_missing")

    if manifest.get("version") != CURRENT_PREFLIGHT_MANIFEST_VERSION:
        failures.append("preflight_manifest.version_mismatch")

    manifest_channel = str(manifest.get("channel") or "").casefold()
    if normalized_channel and manifest_channel and manifest_channel != normalized_channel:
        failures.append("preflight_manifest.channel_mismatch")

    rulebook = manifest.get("rulebook") or {}
    if not isinstance(rulebook, dict) or not rulebook.get("loaded") or not rulebook.get("path") or not rulebook.get("channel_rules_loaded"):
        failures.append("preflight_manifest.rulebook_not_loaded")

    strategy = manifest.get("strategy") or {}
    if not isinstance(strategy, dict) or not strategy.get("source") or not strategy.get("result_path") or not strategy.get("summary"):
        failures.append("preflight_manifest.strategy_missing")

    skills = _skill_set(manifest.get("skills_loaded"))
    required_skills = required_skills_for_channel(normalized_channel)
    if _content_uses_knowledge_cards(packet, manifest):
        required_skills.add("content/knowledge-card-designer")
    missing_skills = sorted(required_skills - skills)
    if missing_skills:
        failures.append("preflight_manifest.skills_missing:" + ",".join(missing_skills))

    visual = manifest.get("visual_policy") or {}
    if not isinstance(visual, dict) or not visual.get("loaded") or not visual.get("policy_id"):
        failures.append("preflight_manifest.visual_policy_missing")

    topic = manifest.get("topic_plan") or {}
    if not isinstance(topic, dict) or not all(_present(topic.get(key)) for key in ["selected_topic", "selection_reason", "content_angle"]):
        failures.append("preflight_manifest.topic_plan_incomplete")

    assets = manifest.get("asset_requirements") or {}
    if not isinstance(assets, dict) or not _present(assets.get("required_assets")) or not _present(assets.get("source_policy")):
        failures.append("preflight_manifest.asset_requirements_incomplete")

    quality_gates = manifest.get("quality_gates") or []
    if not isinstance(quality_gates, list) or len([item for item in quality_gates if _present(item)]) < 3:
        failures.append("preflight_manifest.quality_gates_incomplete")

    publish = manifest.get("publish_constraints") or {}
    if not isinstance(publish, dict) or not publish.get("delivery_health_required") or not publish.get("postcheck_required"):
        failures.append("preflight_manifest.publish_constraints_incomplete")

    from .run_contract import validate_run_contract

    contract_gate = validate_run_contract(manifest.get("run_contract"))
    failures.extend(contract_gate.get("failures") or [])

    return _result(failures, manifest)


def _content_uses_knowledge_cards(packet: dict[str, Any], manifest: dict[str, Any]) -> bool:
    content_type = str(manifest.get("content_type") or packet.get("content_form") or "").casefold()
    if any(hint in content_type for hint in KNOWLEDGE_CARD_CONTENT_HINTS):
        return True
    return bool(packet.get("knowledge_card_plan") or packet.get("embedded_knowledge_cards") or packet.get("knowledge_card_sequence"))


def _content_uses_visual_media(packet: dict[str, Any], manifest: dict[str, Any]) -> bool:
    content_type = str(manifest.get("content_type") or packet.get("content_form") or "").casefold()
    visual_hints = {
        "article",
        "video",
        "card",
        "image",
        "note",
        "infographic",
        "poster",
    }
    return any(hint in content_type for hint in visual_hints) or bool(
        packet.get("visual_content_policy")
        or packet.get("cover_design")
        or packet.get("section_image_map")
        or packet.get("source_assets")
        or packet.get("knowledge_card_sequence")
    )


def _skill_set(value: Any) -> set[str]:
    result: set[str] = set()
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or item.get("skill") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            result.add(name)
            if name.startswith("hermes_skill:"):
                result.add(name.removeprefix("hermes_skill:"))
    return result


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _dict_value(packet: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = packet.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _result(failures: list[str], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "passed": not failures,
        "failed_dimensions": failures,
        "manifest_version": (manifest or {}).get("version", ""),
    }
