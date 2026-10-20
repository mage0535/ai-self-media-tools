"""Deterministic prompt and keyword compilation for content workflows.

This module intentionally stays offline and side-effect free.  It turns a small
content intent specification into reusable prompt sections, search keyword
families, and a quality contract.  Expensive model calls belong in an offline
evaluation layer, not in this hot path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .prompt_registry import PromptRegistry

VERSION = "prompt_bundle_v1"

_AI_SCENARIO_FIELDS = (
    "actor",
    "inputs",
    "process",
    "outcome",
    "boundaries",
    "human_handoff",
    "evidence_status",
)
_EVIDENCE_STATUSES = {"verified", "assumption", "hypothesis", "verification_required"}

_FAILURE_RULES = {
    "input_invalid": (
        "missing_",
        "invalid_",
        "empty_",
        "unsupported_platform",
        "topic_too_short",
        "constraint_missing",
    ),
    "provider_failure": (
        "http 429",
        "http 5",
        "timeout",
        "rate limit",
        "quota",
        "connection reset",
        "provider",
    ),
    "quality_failure": (
        "semantic_asset_mismatch",
        "visual_gate",
        "subtitle",
        "audio_missing",
        "unreadable",
        "duplicate_style",
        "low_contrast",
    ),
    "pipeline_failure": (
        "checkpoint",
        "manifest",
        "state mismatch",
        "renderer mismatch",
        "stale_cache",
        "stale cache",
    ),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_text(value)] if _text(value) else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_text(item) for item in value if _text(item)]
    return []


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint_bundle(bundle: Mapping[str, Any]) -> str:
    """Return a stable content fingerprint excluding the fingerprint itself."""
    payload = {key: value for key, value in bundle.items() if key != "fingerprint"}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def _platform_terms(platform: str, profile: Mapping[str, Any]) -> list[str]:
    return [platform.replace("_", " "), _text(profile.get("prompt_profile"))]


def _topic_terms(topic: str) -> list[str]:
    compact = re.sub(r"\s+", " ", topic).strip()
    return [compact] if compact else []


def _valid_scenario(scenario: Any) -> bool:
    if not isinstance(scenario, Mapping) or any(field not in scenario for field in _AI_SCENARIO_FIELDS):
        return False
    actor = scenario.get("actor")
    inputs = scenario.get("inputs")
    process = scenario.get("process")
    outcome = scenario.get("outcome")
    boundaries = scenario.get("boundaries")
    handoff = scenario.get("human_handoff")
    return bool(
        isinstance(actor, Mapping)
        and all(_text(actor.get(key)) for key in ("role", "context"))
        and isinstance(inputs, list)
        and inputs
        and all(isinstance(row, Mapping) and all(_text(row.get(key)) for key in ("type", "source", "example_or_schema")) for row in inputs)
        and isinstance(process, Mapping)
        and isinstance(process.get("steps"), list)
        and len(process["steps"]) >= 2
        and all(isinstance(row, Mapping) and all(_text(row.get(key)) for key in ("action", "ai_function", "output")) for row in process["steps"])
        and isinstance(outcome, Mapping)
        and all(_text(outcome.get(key)) for key in ("deliverable", "measurement_method", "value_or_verification"))
        and outcome.get("status") in {"measured", "hypothesis", "verification_required"}
        and isinstance(boundaries, list)
        and boundaries
        and all(isinstance(row, Mapping) and _text(row.get("detail")) for row in boundaries)
        and isinstance(handoff, Mapping)
        and all(_text(handoff.get(key)) for key in ("trigger", "responsible_role", "review_or_action", "acceptance_or_escalation_rule"))
        and scenario.get("evidence_status") in _EVIDENCE_STATUSES
    )


def _visual_terms(topic: str, style: str) -> list[str]:
    terms = _topic_terms(topic)
    style_terms = [part.strip() for part in re.split(r"[+,，；;]", style) if part.strip()]
    return list(dict.fromkeys(terms + style_terms + ["真实工作场景", "留出文字安全区"]))


def _prompt_sections(
    spec: Mapping[str, Any], keywords: Mapping[str, list[str]], scenario: Mapping[str, Any] | None = None
) -> dict[str, str]:
    platform = _text(spec.get("platform"))
    content_type = _text(spec.get("content_type"))
    topic = _text(spec.get("topic"))
    audience = _text(spec.get("audience"))
    goal = _text(spec.get("goal"))
    evidence = _list(spec.get("evidence"))
    style = _text(spec.get("visual_style"))
    duration = _text(spec.get("duration"))
    constraints = _list(spec.get("constraints"))
    evidence_text = "、".join(evidence) or "只使用可验证证据"
    constraint_text = "、".join(constraints) or "不得使用随机占位素材"
    scenario_text = ""
    if scenario:
        scenario_text = "\ncanonical_scenario=" + json.dumps(
            {field: scenario[field] for field in _AI_SCENARIO_FIELDS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    topic_prompt = (
        f"平台：{platform}\n内容类型：{content_type}\n主题：{topic}\n"
        f"受众：{audience}\n目标：{goal}\n证据：{evidence_text}\n"
        f"硬约束：{constraint_text}{scenario_text}"
    )
    copy_prompt = (
        f"围绕“{topic}”为{audience}写{content_type}。目标是{goal}。"
        f"先给具体结果或冲突，再给方法和证据；只使用以下证据：{evidence_text}。"
        f"语气要口语、具体、像真实操作者，不写空泛的效率宣言。"
    )
    visual_prompt = (
        f"主体：{topic}；环境：真实工作场景；光线：自然或屏幕环境光；"
        f"风格：{style or '写实、电影感、信息可视化'}；构图：移动端安全区，主体清晰，"
        f"为标题和字幕预留空间。禁止：{constraint_text}。"
    )
    video_prompt = (
        f"制作{platform}的{duration or '短视频'}：3秒钩子→痛点→真实操作→结果证据→单一CTA。"
        f"主题为“{topic}”，受众是{audience}，目标是{goal}。"
        f"每个段落必须绑定一个可验证画面，不得用空洞大字卡。"
    )
    return {
        "topic": topic_prompt,
        "copy": copy_prompt,
        "visual": visual_prompt,
        "video": video_prompt,
    }


def compile_prompt_bundle(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Compile intent into deterministic prompts, keywords, and gates."""
    if not isinstance(spec, Mapping):
        raise TypeError("spec must be a mapping")
    platform_id = _text(spec.get("platform")) or "generic_image"
    registry = PromptRegistry.from_default()
    registry_platform_id = {"douyin_pet": "douyin_ai"}.get(platform_id, platform_id)
    profile = registry.platform(registry_platform_id)
    scenario_value = spec.get("scenario")
    scenario = dict(scenario_value) if isinstance(scenario_value, Mapping) else {}
    requested_profile = _text(spec.get("policy_profile"))
    requested_lane = _text(spec.get("lane"))
    is_ai_lane = bool(scenario) or (
        bool(requested_profile) and requested_profile == _text(profile.get("policy_profile"))
    ) or requested_lane in {
        "real_world_ai_implementation", "real_world_ai_implementation_v1"
    }
    contract: dict[str, str] = {}
    if is_ai_lane:
        expected_contract = {
            "policy_profile": _text(profile.get("policy_profile")),
            "policy_revision": _text(profile.get("policy_revision")),
            "prompt_profile": _text(profile.get("prompt_profile")),
        }
        for field, expected in expected_contract.items():
            actual = _text(spec.get(field))
            if actual != expected:
                raise ValueError(f"{field}_mismatch")
        if not _valid_scenario(scenario):
            raise ValueError("scenario_contract_invalid")
        contract = expected_contract
    user_constraints = _list(spec.get("constraints"))
    profile_constraints = _list(profile.get("required_constraints"))
    requested_content_type = _text(spec.get("content_type"))
    # YouTube is a family, not a single aspect ratio.  Keep the neutral
    # youtube profile neutral and let an explicit content form select the
    # variant without changing the platform routing graph.
    effective_aspect_ratio = profile.get("aspect_ratio")
    effective_content_type = requested_content_type or _text(profile.get("content_type"))
    if platform_id == "youtube":
        if effective_content_type in {"youtube_shorts", "short_video", "shorts"}:
            effective_aspect_ratio = "9:16"
        elif effective_content_type in {"youtube_long_form", "long_video", "longform_video", "video"}:
            effective_aspect_ratio = "16:9" if effective_content_type != "video" else None
    normalized = {
        "platform": platform_id,
        "content_type": effective_content_type,
        "topic": _text(spec.get("topic")),
        "audience": _text(spec.get("audience")),
        "goal": _text(spec.get("goal")),
        "evidence": _list(spec.get("evidence")),
        "visual_style": _text(spec.get("visual_style")),
        "duration": _text(spec.get("duration")),
        "user_constraints": user_constraints,
        "constraints": list(dict.fromkeys(user_constraints + profile_constraints)),
        "language": _text(profile.get("language")),
        "aspect_ratio": effective_aspect_ratio,
    }
    keywords = {
        "platform": _platform_terms(normalized["platform"], profile),
        "topic": _topic_terms(normalized["topic"]),
        "visual": _visual_terms(normalized["topic"], normalized["visual_style"]),
        "evidence": normalized["evidence"],
    }
    bundle = {
        "version": VERSION,
        "contract": contract,
        "scenario": scenario if is_ai_lane else {},
        "input": normalized,
        "keywords": keywords,
        "prompts": _prompt_sections(normalized, keywords, scenario if is_ai_lane else None),
        "quality_contract": {
            "registry_version": registry.version,
            "language": normalized["language"],
            "aspect_ratio": normalized["aspect_ratio"],
            "duration_required": profile.get("duration_seconds") is not None,
            "duration_limits": profile.get("duration_seconds"),
            "evidence_required": True,
            "semantic_asset_match_required": True,
            "platform_constraints_required": True,
            "negative_constraints_required": True,
            "forbidden": _list(profile.get("forbidden")),
        },
    }
    bundle["fingerprint"] = fingerprint_bundle(bundle)
    return bundle


def validate_prompt_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate identity, content, and integrity without attempting repair."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(bundle, Mapping):
        return {"passed": False, "errors": ["bundle_not_mapping"], "warnings": []}
    if bundle.get("version") != VERSION:
        errors.append("bundle_version_mismatch")
    source_value = bundle.get("input")
    source: Mapping[str, Any] = source_value if isinstance(source_value, Mapping) else {}
    if not _text(source.get("topic")):
        errors.append("missing_topic")
    if not _text(source.get("audience")):
        errors.append("missing_audience")
    platform = _text(source.get("platform"))
    if not platform:
        errors.append("missing_platform")
    if not _list(source.get("user_constraints")):
        errors.append("missing_constraints")
    if not _list(source.get("evidence")):
        errors.append("missing_evidence")
    if not isinstance(bundle.get("keywords"), Mapping):
        errors.append("missing_keywords")
    prompts = bundle.get("prompts")
    if not isinstance(prompts, Mapping):
        errors.append("missing_prompts")
    else:
        for prompt_name in ("topic", "copy", "visual", "video"):
            if not _text(prompts.get(prompt_name)):
                errors.append(f"empty_prompt:{prompt_name}")
    try:
        registry = PromptRegistry.from_default()
        registry_platform = {"douyin_pet": "douyin_ai"}.get(platform, platform)
        profile = registry.platform(registry_platform) if platform else {}
        contract_value = bundle.get("contract")
        scenario_value = bundle.get("scenario")
        if (isinstance(contract_value, Mapping) and bool(contract_value)) or (
            isinstance(scenario_value, Mapping) and bool(scenario_value)
        ):
            contract = bundle.get("contract") if isinstance(bundle.get("contract"), Mapping) else {}
            expected = {
                "policy_profile": profile.get("policy_profile"),
                "policy_revision": profile.get("policy_revision"),
                "prompt_profile": profile.get("prompt_profile"),
            }
            if dict(contract) != expected:
                errors.append("canonical_contract_mismatch")
            if not _valid_scenario(bundle.get("scenario")):
                errors.append("scenario_contract_invalid")
    except (KeyError, TypeError, ValueError):
        errors.append("registry_contract_invalid")
    fingerprint = _text(bundle.get("fingerprint"))
    if not fingerprint or fingerprint != fingerprint_bundle(bundle):
        errors.append("fingerprint_mismatch")
    if _text(source.get("content_type")) in {"short_video", "video"} and not _text(source.get("duration")):
        warnings.append("missing_duration")
    return {"passed": not errors, "errors": list(dict.fromkeys(errors)), "warnings": warnings}


def classify_failure(reason: str) -> str:
    """Map a gate/provider error to a bounded retry strategy category."""
    normalized = _text(reason).lower()
    for category, markers in _FAILURE_RULES.items():
        if any(marker in normalized for marker in markers):
            return category
    return "unknown"
