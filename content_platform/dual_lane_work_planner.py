"""Build bounded, platform-specific plans from public and owned evidence lanes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intelligence_provenance import can_use, validate_envelope
from .owned_performance_audit import audit_owned_performance_rows
from .real_world_ai_policy import classify_discovery_text, load_real_world_ai_positioning

ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = ROOT / "config" / "platform_work_planning_profiles_v1.json"


def _profiles() -> dict[str, Any]:
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8")).get("platforms") or {}


def _scenario(title: str, platform: str) -> dict[str, str]:
    actors = {"wechat": "一线运营人员", "douyin_ai": "办公室职员", "kuaishou": "小店经营者", "tiktok": "busy support lead", "youtube": "team operator", "bilibili": "技术或运营负责人", "zhihu": "需要决策的职场用户", "juejin": "开发工程师"}
    actor = actors.get(platform, "需要完成真实任务的人")
    return {
        "actor": actor,
        "inputs": "一组可授权、可打码的真实任务输入",
        "process": "AI先完成低风险的整理、分类或草稿步骤，再由人复核",
        "outcome": "可核验的中间产物或待确认清单",
        "boundaries": "不得把AI输出直接用于高风险或不可逆决定；敏感信息必须脱敏",
        "human_handoff": f"{actor}核对异常、风险和最终决定",
    }


def _eligible_public(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for row in rows:
        check = validate_envelope(row)
        envelope = check["envelope"]
        if not check["passed"] or str(envelope.get("origin_platform") or "").casefold() != platform:
            continue
        if not can_use(envelope, "topic_planning")["allowed"]:
            continue
        # A public title is the only deterministic lane gate. Excerpts can be
        # truncated, injected with unrelated feed metadata, or change later.
        positioning = classify_discovery_text(str(envelope.get("title") or ""))
        if positioning.get("accepted"):
            accepted.append({**envelope, "positioning": positioning})
    return accepted


def build_work_plan(*, platform: str, lane: str, public_observations: list[dict[str, Any]] | None = None, owned_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a manual-review plan; never creates a job or changes learning state."""
    platform = str(platform or "").casefold().strip()
    policy = load_real_world_ai_positioning()
    if platform not in set(policy.get("platforms") or []):
        return {"version": "dual_lane_work_plan_v1", "platform": platform, "lane": lane, "decision": "blocked", "reason_codes": ["platform_not_in_canonical_ai_policy"]}
    if lane != policy.get("policy_profile"):
        return {"version": "dual_lane_work_plan_v1", "platform": platform, "lane": lane, "decision": "blocked", "reason_codes": ["noncanonical_ai_lane"]}
    profiles = _profiles()
    if platform not in profiles:
        return {"version": "dual_lane_work_plan_v1", "platform": platform, "lane": lane, "decision": "blocked", "reason_codes": ["platform_planning_profile_missing"]}
    public = _eligible_public(list(public_observations or []), platform)
    owned_review = audit_owned_performance_rows(list(owned_rows or []))
    if not public:
        return {"version": "dual_lane_work_plan_v1", "platform": platform, "lane": lane, "decision": "blocked", "reason_codes": ["no_eligible_public_signal"], "owned_review": owned_review}
    sample, profile = public[0], profiles[platform]
    scenario = _scenario(str(sample.get("title") or ""), platform)
    public_ids = [str(row["evidence_id"]) for row in public]
    return {
        "version": "dual_lane_work_plan_v1", "platform": platform, "lane": lane,
        "decision": "review_required", "approval_state": "review_required",
        "planning_mode": "public_signal_candidate", "generation_only": True,
        "permissions": {"allow_viral_claims": False, "allow_automated_learning": False},
        "evidence_refs": {"public_web_observation": public_ids, "authorized_owned_analytics": []},
        "signal_summary": {"sample_count": len(public), "source_classes": ["public_web_observation"]},
        "owned_review": owned_review,
        "topic": str(sample.get("title") or ""), "content_form": profile["content_form"],
        "hook_hypothesis": profile["hook"], "narrative_structure": list(profile["structure"]),
        "success_metric": profile["success_metric"], "scenario_contract": scenario,
        "reason_codes": ["public_signal_requires_human_review"],
    }
