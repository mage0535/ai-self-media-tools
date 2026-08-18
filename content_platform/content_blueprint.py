"""Deterministic platform/topic analysis contract before content generation."""

from __future__ import annotations

from typing import Any


PLATFORM_DEFAULTS = {
    "wechat": ("long_article", "experience_led_case_and_checklist"),
    "zhihu": ("evidence_answer", "argument_with_counterexample"),
    "juejin": ("technical_article", "implementation_with_code_and_proof"),
    "kuaishou": ("short_video", "fast_practical_hook_and_save_value"),
    "douyin_ai": ("short_video", "conflict_demo_payoff"),
    "douyin_pet": ("short_video", "cute_behavior_then_safety_value"),
    "bilibili": ("landscape_video", "deep_demo_with_chapters"),
    "xiaohongshu": ("manual_carousel", "saveable_visual_checklist"),
    "youtube": ("short_video", "tutorial_with_visual_proof"),
    "tiktok": ("short_video", "fast_hook_demo_open_question"),
    "twitter": ("short_post", "compact_evidence_backed_viewpoint"),
}


def build_content_blueprint(platform: str, topic: str, slot: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    normalized = str(platform or "").casefold()
    default_form, default_style = PLATFORM_DEFAULTS.get(normalized, ("article", "platform_specific_practical_explanation"))
    keywords = [str(item) for item in slot.get("topic_keywords") or []]
    ai_lane = any(value in (str(topic) + " " + " ".join(keywords)).casefold() for value in ("ai", "agent", "llm", "人工智能", "智能体", "大模型"))
    samples = list((matrix.get("trend_evidence") or {}).get("samples") or [])
    evidence_refs = [str(row.get("url") or row.get("source") or "") for row in samples if isinstance(row, dict)]
    blueprint = {
        "version": "content_blueprint_v1",
        "platform": normalized,
        "topic": str(topic or "").strip(),
        "account_lane": str(slot.get("account_lane") or "AI practical workflows" if ai_lane else slot.get("lane") or normalized),
        "audience": str(slot.get("audience") or "platform users seeking a practical, verifiable result"),
        "user_pain": str(slot.get("user_pain") or f"the audience cannot reliably apply {topic} after consuming generic content"),
        "content_goal": str(slot.get("content_goal") or "deliver one useful result that earns completion, saves, and substantive comments"),
        "content_form": str(slot.get("content_form") or slot.get("stage") or default_form),
        "platform_style": str(slot.get("platform_style") or default_style),
        "narrative_structure": list(slot.get("narrative_structure") or ["hook", "problem", "evidence", "method", "counterexample", "takeaway", "open_question"]),
        "evidence_refs": [item for item in evidence_refs if item],
        "facts_must_come_from_evidence": True,
        "cross_platform_copy_reuse_forbidden": True,
        "mascot_roles": {},
    }
    if ai_lane:
        blueprint["mascot_roles"] = {
            "cat": {"tone": "cute_playful", "narrative_function": f"explore or draft the {topic} workflow", "decorative_only": False},
            "dog": {"tone": "alert_supportive", "narrative_function": f"verify evidence and guard the {topic} result", "decorative_only": False},
        }
    return blueprint


def validate_content_blueprint(blueprint: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(blueprint, dict):
        return {"passed": False, "failures": ["content_blueprint_missing"]}
    for field in ("platform", "topic", "account_lane", "audience", "user_pain", "content_goal", "content_form", "platform_style"):
        if not str(blueprint.get(field) or "").strip():
            failures.append(f"{field}_missing")
    if str(blueprint.get("platform_style") or "").casefold() in {"generic", "default", "same_for_all_platforms"}:
        failures.append("platform_style_generic")
    if len(blueprint.get("narrative_structure") or []) < 5:
        failures.append("narrative_structure_incomplete")
    roles = blueprint.get("mascot_roles") or {}
    for role in roles.values():
        if not isinstance(role, dict) or not role.get("narrative_function") or role.get("decorative_only") is not False:
            failures.append("mascot_role_not_functional")
            break
    return {"passed": not failures, "failures": sorted(set(failures))}
