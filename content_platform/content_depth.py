"""Small, explicit depth contract for generated articles and video scripts."""

from __future__ import annotations

import re
from typing import Any


_CONTINUATION = re.compile(r"(?:next (?:episode|part|post)|to be continued|下一[期集篇]|后续.*(?:讲|看|分享))", re.IGNORECASE)


def build_content_depth_plan(
    title: str,
    body: str,
    *,
    evidence: list[str] | None = None,
    actions: list[str] | None = None,
    series_plan: dict[str, Any] | None = None,
    platform: str = "",
) -> dict[str, Any]:
    """Describe actionable value without inventing research or a sequel."""
    lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
    action_steps = [str(item).strip() for item in (actions or []) if str(item).strip()]
    if not action_steps:
        action_steps = [line for line in lines if len(line) >= 12][:3]
    evidence_rows = [str(item).strip() for item in (evidence or []) if str(item).strip()]
    continuation_claimed = bool(_CONTINUATION.search(str(body or "")))
    return {
        "version": "content_depth_plan_v1",
        "title": str(title or "").strip(),
        "depth_layers": {
            "problem": bool(lines),
            "evidence": evidence_rows,
            "method": lines[:3],
            "actions": action_steps,
        },
        "actions": action_steps,
        "evidence": evidence_rows,
        "core_question": str(title or "").strip(),
        "user_pain": lines[0] if lines else "",
        "knowledge_points": action_steps[:3],
        "case_or_demo": evidence_rows[0] if evidence_rows else "",
        "steps": action_steps,
        "counterexample": "Avoid publishing a generic claim without a measurable example.",
        "takeaway": action_steps[-1] if action_steps else "",
        "interaction_prompt": "Which step would you test first?",
        "platform_style": _platform_style(platform),
        "continuation_claimed": continuation_claimed,
        "series_plan": dict(series_plan or {}),
    }


def validate_content_depth_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(plan, dict) or not plan:
        failures.append("content_depth_plan_missing")
    else:
        if plan.get("version") != "content_depth_plan_v1":
            failures.append("content_depth_plan_version_invalid")
        if not str(plan.get("title") or "").strip():
            failures.append("content_depth_title_missing")
        if len(plan.get("actions") or []) < 2:
            failures.append("action_steps_insufficient")
        if len(plan.get("evidence") or []) < 1:
            failures.append("evidence_insufficient")
        if len(plan.get("knowledge_points") or []) < 3:
            failures.append("knowledge_points_insufficient")
        for field in ("case_or_demo", "steps", "counterexample", "takeaway", "interaction_prompt"):
            if not plan.get(field):
                failures.append(f"{field}_missing")
        if plan.get("continuation_claimed"):
            series = plan.get("series_plan") if isinstance(plan.get("series_plan"), dict) else {}
            if not str(series.get("next_topic") or "").strip() or not str(series.get("delivery_window") or "").strip():
                failures.append("continuation_without_series_plan")
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["content_depth"] if failures else []}


def _platform_style(platform: str) -> str:
    key = str(platform or "").casefold()
    return {
        "zhihu": "argument_with_evidence",
        "juejin": "implementation_with_examples",
        "wechat": "experience_synthesis",
        "kuaishou": "fast_hook_then_payoff",
        "douyin": "fast_hook_then_payoff",
        "x": "compact_point_of_view",
    }.get(key, "platform_adapted_practical_explanation")
