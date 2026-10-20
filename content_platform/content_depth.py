"""Machine-checkable depth contract for articles and video scripts."""

from __future__ import annotations

import re
from typing import Any


CONTINUATION = re.compile(r"(?:next (?:episode|part|post)|to be continued|下一[期集篇]|后续.*(?:讲|看|分享))", re.I)


def claims_continuation(body: str) -> bool:
    """An in-document reading direction is not a promise of another release."""
    text=str(body or "")
    for match in CONTINUATION.finditer(text):
        if match.group(0).casefold()!='next part':
            return True
        start=max(text.rfind(mark,0,match.start())for mark in ('.','!','?','\n'))+1
        stops=[position for mark in ('.','!','?','\n')if (position:=text.find(mark,match.end()))>=0]
        stop=min(stops)if stops else len(text)
        sentence=text[start:stop].strip()
        following=text[stop+1:].lstrip()
        next_stop=re.search(r"[.!?\n]",following)
        following=following[:next_stop.start()]if next_stop else following
        same_document=(re.fullmatch(r"(?:read|review)\s+the\s+next\s+part\s+carefully\s+before\s+acting\s+on\s+(?:any\s+of\s+)?it",sentence,re.I)
            and re.fullmatch(r"\s*what\s+follows\s+is\s+a\s+proposed\s+(?:review\s+)?method(?:,\s*not\s+a\s+deployment\s+log)?\s*",following,re.I))
        if not same_document:
            return True
    return False


def build_content_depth_plan(
    title: str,
    body: str,
    *,
    evidence: list[str] | None = None,
    actions: list[str] | None = None,
    series_plan: dict[str, Any] | None = None,
    platform: str = "",
) -> dict[str, Any]:
    cleaned_body = re.sub(r"var\s+glb[^\n]*", "", str(body or ""))
    cleaned_body = re.sub(r'\(glb\s*=\s*"undefined"[^\n]*', "", cleaned_body)
    cleaned_body = re.sub(r"typeof\s+window[^\n]*", "", cleaned_body)
    lines = [line.strip(" -#\t") for line in cleaned_body.splitlines() if line.strip()]
    # 过滤纯 JS 残留行
    js_noise = re.compile(r"^(var|let|const|glb|undefined|typeof|window)\b", re.I)
    lines = [line for line in lines if not js_noise.search(line) and len(line) > 1]
    action_steps = [str(item).strip() for item in (actions or []) if str(item).strip()]
    if len(action_steps) < 3:
        candidates = [line for line in lines if len(line) >= 12]
        action_steps.extend(item for item in candidates if item not in action_steps)
    action_steps = action_steps[:5]
    evidence_rows = [str(item).strip() for item in (evidence or []) if str(item).strip()]
    return {
        "version": "content_depth_plan_v1",
        "title": str(title or "").strip(),
        "core_question": str(title or "").strip(),
        "user_pain": lines[0] if lines else "",
        "knowledge_points": action_steps[:3],
        "case_or_demo": evidence_rows[0] if evidence_rows else "",
        "steps": action_steps,
        "counterexample": "Do not replace missing evidence with a plausible-looking claim.",
        "takeaway": action_steps[-1] if action_steps else "",
        "interaction_prompt": "Which step would you verify first?",
        "evidence": evidence_rows,
        "platform_style": _platform_style(platform),
        "continuation_claimed": claims_continuation(body),
        "series_plan": dict(series_plan or {}),
    }


def validate_content_depth_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(plan, dict) or not plan:
        return {"passed": False, "failures": ["content_depth_plan_missing"], "failed_dimensions": ["content_depth"]}
    if plan.get("version") != "content_depth_plan_v1":
        failures.append("content_depth_plan_version_invalid")
    if not str(plan.get("title") or "").strip():
        failures.append("content_depth_title_missing")
    if len(plan.get("knowledge_points") or []) < 3:
        failures.append("knowledge_points_insufficient")
    if len(plan.get("steps") or []) < 2:
        failures.append("action_steps_insufficient")
    for field in ("case_or_demo", "counterexample", "takeaway", "interaction_prompt"):
        if not plan.get(field):
            failures.append(f"{field}_missing")
    if plan.get("continuation_claimed"):
        series = plan.get("series_plan") if isinstance(plan.get("series_plan"), dict) else {}
        if not str(series.get("next_topic") or "").strip() or not str(series.get("delivery_window") or "").strip():
            failures.append("continuation_without_series_plan")
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["content_depth"] if failures else []}


def _platform_style(platform: str) -> str:
    return {
        "zhihu": "argument_with_evidence",
        "juejin": "implementation_with_examples",
        "wechat": "experience_synthesis",
        "kuaishou": "fast_hook_then_payoff",
        "douyin": "fast_hook_then_payoff",
        "douyin_ai": "fast_hook_then_payoff",
        "douyin_pet": "emotion_then_practical_value",
        "tiktok": "fast_hook_demo_payoff",
        "youtube": "tutorial_with_proof",
        "twitter": "compact_point_of_view",
    }.get(str(platform or "").casefold(), "platform_adapted_practical_explanation")
