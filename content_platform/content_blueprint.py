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


AI_LANE_PLATFORMS = {"kuaishou", "bilibili", "youtube", "tiktok", "xiaohongshu", "wechat", "douyin_ai", "shipinhao", "juejin", "zhihu", "twitter", "douyin"}
AI_TOPIC_WORDS = ("ai", "agent", "llm", "人工智能", "智能体", "大模型")


def _is_ai_lane(platform: str, text: str) -> bool:
    """douyin_pet is the pet_healing lane; every other AI platform, or an AI topic, is an AI lane."""
    if platform == "douyin_pet":
        return False
    return platform in AI_LANE_PLATFORMS or any(word in text.casefold() for word in AI_TOPIC_WORDS)


def build_content_blueprint(
    platform: str,
    topic: str,
    slot: dict[str, Any],
    matrix: dict[str, Any],
    *,
    quality_reference_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(platform or "").casefold()
    default_form, default_style = PLATFORM_DEFAULTS.get(normalized, ("article", "platform_specific_practical_explanation"))
    keywords = [str(item) for item in slot.get("topic_keywords") or []]
    # Same rule as validate_content_blueprint: r51 "Claude Code vs Codex" on juejin got no roles, then failed validation.
    ai_lane = _is_ai_lane(normalized, str(topic) + " " + " ".join(keywords))
    samples = _blueprint_evidence_samples(matrix)
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
    compiled_strategy = slot.get("strategy_compiled") or slot.get("strategy")
    if isinstance(compiled_strategy, dict) and compiled_strategy.get("version") == "compiled_strategy_v1":
        blueprint["strategy_policy"] = {
            "source_sha256": compiled_strategy.get("source_sha256", ""),
            "content_pillars": list(compiled_strategy.get("content_pillars") or [])[:8],
            "structure_pool": list(compiled_strategy.get("structure_pool") or [])[:8],
            "hook_templates": list(compiled_strategy.get("hook_templates") or [])[:8],
            "cta_pool": list(compiled_strategy.get("cta_pool") or [])[:8],
            "evidence_policy": dict(compiled_strategy.get("evidence_policy") or {}),
        }
    if isinstance(quality_reference_pack, dict) and quality_reference_pack.get("loaded") is True:
        sections = [str(item) for item in quality_reference_pack.get("sections") or []]
        blueprint["quality_reference"] = {
            "version": str(quality_reference_pack.get("version") or ""),
            "sha256": str(quality_reference_pack.get("sha256") or ""),
            "sections": sections,
        }
        blueprint["quality_requirements"] = {
            "hook_title_gate": "hook_title_gate" in sections,
            "content_structure_gate": "content_structure_gate" in sections,
            "cover_design_gate": "cover_design_gate" in sections,
            "image_text_card_gate": "image_text_card_gate" in sections,
            "video_director_gate": "video_director_gate" in sections,
            "motion_discipline_gate": "motion_discipline_gate" in sections,
            "compliance_gate": "compliance_gate" in sections,
        }
    if ai_lane:
        blueprint["mascot_roles"] = {
            "cat": {"tone": "cute_playful", "narrative_function": f"explore or draft the {topic} workflow", "decorative_only": False},
            "dog": {"tone": "alert_supportive", "narrative_function": f"verify evidence and guard the {topic} result", "decorative_only": False},
        }
    intelligence_plan = slot.get("dual_lane_work_plan")
    if isinstance(intelligence_plan, dict) and intelligence_plan.get("version") == "dual_lane_work_plan_v1":
        permissions = intelligence_plan.get("permissions") if isinstance(intelligence_plan.get("permissions"), dict) else {}
        scenario = intelligence_plan.get("scenario_contract") if isinstance(intelligence_plan.get("scenario_contract"), dict) else {}
        if (
            intelligence_plan.get("decision") in {"review_required", "planned"}
            and permissions.get("allow_viral_claims") is False
            and permissions.get("allow_automated_learning") is False
            and all(str(scenario.get(key) or "").strip() for key in ("actor", "inputs", "process", "outcome", "boundaries", "human_handoff"))
        ):
            blueprint["intelligence_plan"] = {
                "planning_mode": intelligence_plan.get("planning_mode"),
                "generation_only": True,
                "allow_viral_claims": False,
                "allow_automated_learning": False,
                "hook_hypothesis": intelligence_plan.get("hook_hypothesis"),
                "success_metric": intelligence_plan.get("success_metric"),
                "scenario_contract": scenario,
                "evidence_refs": intelligence_plan.get("evidence_refs") or {},
            }
    _analysis_fields(blueprint, slot, matrix)
    validation = validate_content_blueprint(blueprint)
    if not validation["passed"]:
        raise ValueError("content_blueprint_analysis_failed:" + ",".join(validation["failures"]))
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
    quality_reference = blueprint.get("quality_reference")
    if isinstance(quality_reference, dict):
        if quality_reference.get("version") != "content_quality_reference_pack_v1":
            failures.append("quality_reference_version_mismatch")
        if not quality_reference.get("sha256") or not quality_reference.get("sections"):
            failures.append("quality_reference_incomplete")
    roles = blueprint.get("mascot_roles") or {}
    for role in roles.values():
        if not isinstance(role, dict) or not role.get("narrative_function") or role.get("decorative_only") is not False:
            failures.append("mascot_role_not_functional")
            break
    # AI知识赛道强制猫狗角色（enforced: all_ai_knowledge_content 全平台AI赛道）
    # scope: kuaishou/bilibili/youtube/tiktok/xiaohongshu/wechat/douyin_ai/shipinhao/juejin/zhihu 等所有AI知识形态，douyin_pet 治愈赛道豁免
    topic_text = str(blueprint.get("topic") or "")
    platform_norm = str(blueprint.get("platform") or "").casefold()
    # douyin_pet 为 pet_healing 赛道，永不触发AI猫狗门禁
    if _is_ai_lane(platform_norm, topic_text):
        if not roles or len(roles) < 1:
            failures.append("ai_lane_cat_dog_role_missing")
        for cat_key in ("cat", "dog"):
            if cat_key not in roles:
                pass
    failures.extend(_validate_analysis_fields(blueprint))
    return {"passed": not failures, "failures": sorted(set(failures))}

def _current_analysis_policy(platform: str) -> dict[str, Any]:
    from .run_contract import build_run_contract
    contract = build_run_contract(platform)
    policy = (contract.get("global_hard_gates") or {}).get("topic_platform_content_analysis_policy")
    if not isinstance(policy, dict) or policy.get("enforced") is not True or not policy.get("required_fields"):
        raise ValueError("current_topic_platform_analysis_policy_missing")
    return policy


def _text(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return "" if text.casefold() in {"tbd", "todo", "pending", "n/a", "待补充", "待确定", "占位"} else text


def _scenario(slot: dict[str, Any]) -> dict[str, Any]:
    plan = slot.get("dual_lane_work_plan") or {}
    intent = slot.get("production_intent") or {}
    value = slot.get("scenario_contract") or plan.get("scenario_contract") or intent.get("scenario_contract")
    return dict(value) if isinstance(value, dict) else {}


def _analysis_fields(blueprint: dict[str, Any], slot: dict[str, Any], matrix: dict[str, Any]) -> None:
    """Compile a plan from this task's actual analysis; never from a reference post."""
    topic = blueprint["topic"]
    scenario = _scenario(slot)
    required = ("actor", "inputs", "process", "outcome", "boundaries", "human_handoff")
    complete = all(_text(scenario.get(key)) for key in required)
    supplied = slot.get("topic_analysis") if isinstance(slot.get("topic_analysis"), dict) else {}
    for field in _current_analysis_policy(blueprint["platform"])["required_fields"]:
        if field in supplied and field not in {"platform", "selected_topic"}:
            blueprint[field] = supplied[field]
        elif field in slot and field not in {"platform", "selected_topic"}:
            blueprint[field] = slot[field]
    for inputs in (slot, supplied):
        if inputs.get("platform") not in (None, blueprint["platform"]):
            blueprint["analysis_input_error"] = "analysis_platform_mismatch"
        if inputs.get("selected_topic") not in (None, topic):
            blueprint["analysis_input_error"] = "selected_topic_current_intent_mismatch"
    blueprint.update(
        selected_topic=topic,
        target_audience=blueprint["audience"],
        platform_voice_and_style=blueprint["platform_style"],
    )
    intent = slot.get("production_intent") or {}
    intended_topic = _text(intent.get("topic")) if isinstance(intent, dict) else ""
    if intended_topic and intended_topic != topic:
        blueprint["analysis_input_error"] = "selected_topic_current_intent_mismatch"
    if complete:
        if not _text(slot.get("audience")):
            blueprint["audience"] = scenario["actor"]
            blueprint["target_audience"] = scenario["actor"]
        if not _text(slot.get("user_pain")):
            blueprint["user_pain"] = scenario["boundaries"]
        if not _text(slot.get("content_goal")):
            blueprint["content_goal"] = scenario["outcome"]
        blueprint["scenario_contract"] = scenario
        blueprint.setdefault("core_question", f"{topic}: how should {scenario['actor']} perform {scenario['process']} using {scenario['inputs']}?")
        blueprint.setdefault("reader_or_viewer_payoff", scenario["outcome"])
        blueprint.setdefault("hook_plan", {
            "topic": topic, "audience": blueprint["audience"],
            "problem_or_boundary": scenario["boundaries"], "payoff": scenario["outcome"],
            "source_copy_forbidden": True,
        })
        blueprint.setdefault("knowledge_depth_plan", {
            "topic": topic,
            "knowledge_points": [scenario["inputs"], scenario["process"], scenario["boundaries"]],
            "action_sequence": [scenario["process"], scenario["human_handoff"]],
            "verification_boundary": scenario["outcome"],
            "counterexample_or_limitation": scenario["boundaries"],
        })
        structure = blueprint["narrative_structure"]
        content = {
            "hook": scenario["boundaries"], "problem": scenario["inputs"],
            "evidence": blueprint["evidence_refs"], "method": scenario["process"],
            "counterexample": scenario["boundaries"], "takeaway": scenario["outcome"],
            "open_question": scenario["human_handoff"],
        }
        blueprint.setdefault("content_structure", [
            {"section": name, "task_content": content.get(name, ""), "topic": topic}
            for name in structure
        ])
        blueprint.setdefault("asset_and_evidence_plan", {
            "topic": topic, "evidence_refs": list(blueprint["evidence_refs"]),
            "show_inputs": scenario["inputs"], "show_process": scenario["process"],
            "show_verification": scenario["outcome"], "unverified_boundary": scenario["boundaries"],
            "asset_plan": slot.get("asset_plan") or slot.get("media_plan") or [],
            "facts_must_come_from_evidence": True,
        })
        blueprint.setdefault("adaptive_cover_direction", {
            "topic": topic, "subject": scenario["inputs"], "action": scenario["process"],
            "payoff_or_boundary": scenario["boundaries"], "platform": blueprint["platform"],
            "unverified_outcomes_must_not_be_shown_as_success": True,
        })
        blueprint.setdefault("cta_plan", {
            "topic": topic, "question_about": scenario["human_handoff"],
            "reader_action": scenario["process"], "unverified_boundary": scenario["boundaries"],
        })
    if matrix.get("evidence_domain") == "original_method":
        blueprint["evidence_domain"] = "original_method"
        blueprint["factual_evidence"] = {"source_use": "method_facts_only", "samples": _blueprint_evidence_samples(matrix)}
        assets = blueprint.get("asset_and_evidence_plan")
        if isinstance(assets, dict):
            assets["evidence_domain"] = "original_method"
            assets["source_use"] = "method_facts_only"
            assets["factual_evidence_refs"] = blueprint["factual_evidence"]["samples"]
    roles = blueprint.get("mascot_roles") or {}
    if roles:
        blueprint.setdefault("cat_dog_role_plan_when_ai_knowledge_lane", roles)
    else:
        blueprint.setdefault("cat_dog_role_plan_when_ai_knowledge_lane", {
            "applicable": False, "reason": "current non-AI lane", "platform": blueprint["platform"],
        })
    text_forms = {"article", "long_article", "technical_article", "evidence_answer", "short_post", "social_note", "manual_carousel", "carousel", "image_text", "image_text_post"}
    if blueprint["content_form"].casefold() in text_forms:
        blueprint.setdefault("subtitle_and_pacing_plan_when_video", {
            "applicable": False, "reason": "current content form has no video narration",
            "content_form": blueprint["content_form"],
        })
    # A video plan must come from its actual director/narration inputs, not guessed timings.
    elif "video" in blueprint["content_form"].casefold():
        plan = slot.get("subtitle_and_pacing_plan_when_video") or slot.get("subtitle_and_pacing_plan")
        if isinstance(plan, dict):
            blueprint.setdefault("subtitle_and_pacing_plan_when_video", plan)


def _validate_analysis_fields(blueprint: dict[str, Any]) -> list[str]:
    failures = []
    policy = _current_analysis_policy(str(blueprint.get("platform") or ""))
    for name in policy["required_fields"]:
        value = blueprint.get(name)
        if value in (None, "", [], {}) or isinstance(value, bool):
            failures.append(f"{name}_missing")
    if blueprint.get("selected_topic") != blueprint.get("topic"):
        failures.append("selected_topic_current_topic_mismatch")
    if blueprint.get("analysis_input_error"):
        failures.append(str(blueprint["analysis_input_error"]))
    for field in ("core_question", "reader_or_viewer_payoff", "target_audience", "platform_voice_and_style"):
        if not _text(blueprint.get(field)):
            failures.append(f"{field}_invalid")
    topic = blueprint.get("topic")
    for field in ("hook_plan", "knowledge_depth_plan", "asset_and_evidence_plan", "adaptive_cover_direction", "cta_plan"):
        value = blueprint.get(field)
        if not isinstance(value, dict) or value.get("topic") != topic:
            failures.append(f"{field}_current_topic_required")
    depth = blueprint.get("knowledge_depth_plan") or {}
    if not isinstance(depth, dict) or not isinstance(depth.get("knowledge_points"), list) or len({_text(x) for x in depth.get("knowledge_points", []) if _text(x)}) < 3:
        failures.append("knowledge_depth_plan_concrete_points_missing")
    if not isinstance(depth, dict) or not isinstance(depth.get("action_sequence"), list) or len({_text(x) for x in depth.get("action_sequence", []) if _text(x)}) < 2 or not _text(depth.get("counterexample_or_limitation")):
        failures.append("knowledge_depth_plan_actions_or_boundary_missing")
    structure = blueprint.get("content_structure")
    if not isinstance(structure, list) or len(structure) < 5:
        failures.append("content_structure_incomplete")
    elif any(not isinstance(row, dict) or row.get("topic") != topic or not _text(row.get("section")) or row.get("task_content") in (None, "", [], {}) for row in structure):
        failures.append("content_structure_current_task_content_missing")
    refs = blueprint.get("evidence_refs")
    assets = blueprint.get("asset_and_evidence_plan") or {}
    if not refs or not isinstance(assets, dict) or assets.get("evidence_refs") != refs or assets.get("facts_must_come_from_evidence") is not True:
        failures.append("asset_and_evidence_plan_current_sources_missing")
    for field, fields in {
        "hook_plan": ("problem_or_boundary", "payoff"),
        "adaptive_cover_direction": ("subject", "action", "payoff_or_boundary"),
        "cta_plan": ("question_about", "reader_action", "unverified_boundary"),
    }.items():
        value = blueprint.get(field) or {}
        if not isinstance(value, dict) or any(not _text(value.get(key)) for key in fields):
            failures.append(f"{field}_concrete_task_fields_missing")
    form = str(blueprint.get("content_form") or "").casefold()
    video = "video" in form
    if not video and form not in {"article", "long_article", "technical_article", "evidence_answer", "short_post", "social_note", "manual_carousel", "carousel", "image_text", "image_text_post"}:
        failures.append("content_form_video_applicability_unknown")
    roles = blueprint.get("mascot_roles") or {}
    if roles and (not {"cat", "dog"} <= set(roles) or blueprint.get("cat_dog_role_plan_when_ai_knowledge_lane") != roles):
        failures.append("cat_dog_role_plan_current_roles_mismatch")
    timing = blueprint.get("subtitle_and_pacing_plan_when_video")
    if video and (not isinstance(timing, dict) or timing.get("applicable") is False or not timing.get("segments")):
        failures.append("video_subtitle_and_pacing_plan_missing")
    return failures


def _blueprint_evidence_samples(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    if matrix.get("evidence_domain") != "original_method":
        return list((matrix.get("trend_evidence") or {}).get("samples") or [])
    if matrix.get("trend_evidence"):
        raise ValueError("original_method_facts_cannot_be_trend_evidence")
    rows = (matrix.get("factual_evidence") or {}).get("samples")
    if not isinstance(rows, list) or not rows:
        raise ValueError("original_method_factual_evidence_missing")
    from pathlib import Path
    import hashlib
    import stat
    for row in rows:
        if not isinstance(row, dict) or row.get("source_use") != "method_facts_only":
            raise ValueError("original_method_fact_use_invalid")
        if row.get("source_kind") == "official_factual_reference":
            if not str(row.get("url") or "").startswith("https://"):
                raise ValueError("original_method_official_url_required")
            fields = ("raw_ref",)
        elif row.get("source_kind") == "native_first_party_receipt":
            if not str(row.get("url") or "").startswith("hermes-receipt://morning/"):
                raise ValueError("original_method_native_receipt_url_required")
            fields = ("acceptance_ref", "delivery_ledger_ref", "report_ref")
        else:
            raise ValueError("original_method_fact_kind_invalid")
        for field in fields:
            ref = row.get(field)
            if not isinstance(ref, dict) or not {"path", "sha256"} <= set(ref):
                raise ValueError("original_method_actual_fact_ref_required")
            path = Path(ref["path"])
            if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise ValueError("original_method_actual_fact_path_invalid")
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
                raise ValueError("original_method_actual_fact_not_private")
            if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
                raise ValueError("original_method_actual_fact_changed")
    return rows

