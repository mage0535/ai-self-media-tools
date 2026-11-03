"""Pre-generation evidence manifest for channel content workflows.

The manifest is intentionally small and portable.  It proves that a content
packet was generated from the current rulebook, channel strategy, relevant
skills, visual policy, asset requirements, quality gates, and publish
constraints before media generation or delivery is attempted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
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

REQUIRED_SKILLS_BY_CHANNEL = {
    "wechat": {"meta/content-preflight", "content/content-strategy-workflow", "content/wechat-operational-strategy", "content/visual-quality-standards", "content/wechat-full-workflow", "wewrite", "no-ai-slop"},
    "weixin": {"meta/content-preflight", "content/content-strategy-workflow", "content/wechat-operational-strategy", "content/visual-quality-standards", "content/wechat-full-workflow", "wewrite", "no-ai-slop"},
    "wechat_official": {"meta/content-preflight", "content/content-strategy-workflow", "content/wechat-operational-strategy", "content/visual-quality-standards", "content/wechat-full-workflow", "wewrite", "no-ai-slop"},
    "kuaishou": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "douyin": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "shipinhao": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "bilibili": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "xiaohongshu": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "rednote": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},

    "juejin": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
    "zhihu": {"meta/content-preflight", "content/content-strategy-workflow", "content/knowledge-card-designer", "content/visual-quality-standards"},
}

KNOWLEDGE_CARD_CONTENT_HINTS = {"knowledge_card", "card", "infographic", "image_card"}


def _source_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    data = source.read_bytes()
    if not data:
        raise ValueError(f"preflight source is empty: {source}")
    return {"path": str(source), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _load_source_evidence(channel, skills, workflow_context=None):
    """Read inputs, compile strategy, and retain file evidence rather than names."""
    from . import platform_workflow_context as loader
    from . import visual_content_policy as visual
    from .strategy_compiler import compile_strategy, validate_compiled_strategy

    context = workflow_context or {}
    rulebook = _source_file((context.get("rulebook") or {}).get("path") or loader.RULEBOOK)
    rules = json.loads(Path(rulebook["path"]).read_text(encoding="utf-8"))
    aliases = {"weixin": "wechat", "wechat_official": "wechat", "rednote": "xiaohongshu"}
    entry = (rules.get("channel_rules") or {}).get(aliases.get(channel, channel))
    if not isinstance(entry, dict):
        raise ValueError(f"preflight channel rule missing: {channel}")
    strategy_path = (context.get("strategy") or {}).get("path")
    strategy_path = strategy_path or loader._latest_distilled_strategy() or loader._latest_strategy(channel)
    if not strategy_path:
        raise FileNotFoundError(f"preflight strategy source missing: {channel}")
    strategy = _source_file(strategy_path)
    compiled = compile_strategy(strategy["path"], channel)
    strategy_gate = validate_compiled_strategy(compiled)
    if not strategy_gate.get("passed"):
        raise ValueError("preflight strategy compilation failed")
    records = []
    for name in skills:
        records.append(dict(_source_file(loader._skill_path(name)), name=name))
    return {
        "version": "preflight_source_evidence_v1",
        "rulebook": rulebook,
        "strategy": dict(strategy, compiled=compiled, compiled_gate=strategy_gate),
        "skills": records,
        "visual_policy": _source_file(visual.__file__),
        "executed_checks": ["read_current_rulebook", "compile_actual_strategy", "read_required_skill_bytes", "read_visual_policy_source"],
    }


def _validate_source_evidence(manifest, channel, required_skills):
    from . import platform_workflow_context as loader
    from . import visual_content_policy as visual
    from .strategy_compiler import compile_strategy, validate_compiled_strategy

    evidence = manifest.get("source_evidence") or {}
    failures = []
    if not isinstance(evidence, dict) or evidence.get("version") != "preflight_source_evidence_v1":
        return ["preflight_manifest.source_evidence_missing"]
    records = evidence.get("skills") or []
    if not isinstance(records, list):
        return ["preflight_manifest.skill_file_evidence_missing"]
    names = {str(row.get("name") or "") for row in records if isinstance(row, dict)}
    if not required_skills.issubset(names):
        failures.append("preflight_manifest.skill_file_evidence_missing")
    sources = [(key, evidence.get(key)) for key in ("rulebook", "strategy", "visual_policy")]
    sources.extend(("skill:" + str(row.get("name") or ""), row) for row in records if isinstance(row, dict))
    canonical = {"rulebook": loader.RULEBOOK, "visual_policy": visual.__file__}
    canonical.update(("skill:" + name, loader._skill_path(name)) for name in required_skills)
    for name, row in sources:
        try:
            actual = _source_file(row["path"])
            if actual["sha256"] != row.get("sha256") or actual["bytes"] != row.get("bytes"):
                failures.append("preflight_manifest.source_changed:" + name)
            if name in canonical and Path(actual["path"]) != Path(canonical[name]).resolve():
                failures.append("preflight_manifest.source_path_mismatch:" + name)
        except (OSError, ValueError, KeyError, TypeError):
            failures.append("preflight_manifest.source_unreadable:" + name)
    try:
        strategy = evidence["strategy"]
        compiled = compile_strategy(strategy["path"], channel)
        if compiled != strategy.get("compiled") or not validate_compiled_strategy(compiled).get("passed"):
            failures.append("preflight_manifest.strategy_recompile_mismatch")
        if (manifest.get("run_contract") or {}).get("rulebook", {}).get("sha256") != evidence["rulebook"]["sha256"]:
            failures.append("preflight_manifest.rulebook_contract_mismatch")
    except (OSError, ValueError, KeyError, TypeError):
        failures.append("preflight_manifest.strategy_recompile_failed")
    return failures


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
    workflow_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical manifest that generators should attach to packets."""
    normalized_channel = str(channel or "").casefold()
    skills = sorted(
        set(REQUIRED_SKILLS_BY_CHANNEL.get(normalized_channel, {"meta/content-preflight", "content/content-strategy-workflow"}))
        | set(extra_skills or [])
    )
    from .run_contract import build_run_contract

    source_evidence = _load_source_evidence(normalized_channel, skills, workflow_context)

    return {
        "version": CURRENT_PREFLIGHT_MANIFEST_VERSION,
        "channel": normalized_channel,
        "content_type": content_type,
        "rulebook": {
            "loaded": True,
            **source_evidence["rulebook"],
            "channel_rules_loaded": True,
        },
        "strategy": {
            "source": strategy_source,
            "result_path": strategy_result_path,
            "summary": strategy_summary,
            "source_file": source_evidence["strategy"],
        },
        "skills_loaded": skills,
        "source_evidence": source_evidence,
        "visual_policy": {
            "loaded": True,
            "policy_id": "visual_content_design_policy_v1",
            **source_evidence["visual_policy"],
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

    from .body_visual_gate import preflight_handoff_failures

    handoff_failures = preflight_handoff_failures(packet)
    if not manifest:
        return _result(["preflight_manifest_missing", *handoff_failures])

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
    required_skills = set(REQUIRED_SKILLS_BY_CHANNEL.get(normalized_channel, {"meta/content-preflight", "content/content-strategy-workflow"}))
    if _content_uses_knowledge_cards(packet, manifest):
        required_skills.add("content/knowledge-card-designer")
    missing_skills = sorted(required_skills - skills)
    if missing_skills:
        failures.append("preflight_manifest.skills_missing:" + ",".join(missing_skills))
    failures.extend(_validate_source_evidence(manifest, normalized_channel, required_skills))

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
    failures.extend(handoff_failures)

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
