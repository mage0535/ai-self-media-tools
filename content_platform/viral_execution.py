"""Turn observed viral-reference evidence into bounded generation policy.

This is intentionally a small execution boundary: the report remains evidence,
while this policy is the only shape generation and rendering code consumes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


POLICY_FIELDS = (
    "analysis_id", "selected_hook", "content_promise", "narrative_engine",
    "evidence_sequence", "writing_style", "visual_mode", "motion_function",
    "transition_semantics", "anti_template_constraints", "reference_ids",
)


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item) for item in value if _text(item)][:limit]


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pick(sample: Any, *keys: str) -> Any:
    for key in keys:
        value = sample.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def build_viral_execution_policy(
    report: dict[str, Any] | None, *, eligibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, deterministic policy from a validated report.

    A ready report with no accepted evidence is rejected here as well as at the
    topic gate. This prevents callers from treating a status flag as analysis.
    """
    report = report if isinstance(report, dict) else {}
    eligibility = eligibility if isinstance(eligibility, dict) else {}
    permissions = eligibility.get("permissions") or {}
    if eligibility.get("state") not in {"S5_ADVISE", "S6_AUTO_LEARN"} or permissions.get("allow_advice") is not True:
        raise ValueError("viral_execution_advice_not_eligible")
    validation = report.get("validation") or {}
    summary = report.get("summary") or {}
    samples = report.get("samples") or []
    if report.get("status") != "ready" or validation.get("passed") is False:
        raise ValueError("viral_breakdown_not_ready")
    if not samples or int(summary.get("accepted_samples", 0) or 0) <= 0:
        raise ValueError("viral_breakdown_has_no_accepted_samples")

    sample = next((item for item in samples if isinstance(item, dict)), {})
    copy = _pick(sample, "copy_or_script", "copy_structure")
    structure = _pick(sample, "content_structure", "structure")
    style = _pick(sample, "writing_style", "style")
    theme = sample.get("theme_template") if isinstance(sample.get("theme_template"), dict) else {}
    motion = sample.get("motion_combination") if isinstance(sample.get("motion_combination"), dict) else {}
    transition = sample.get("transition_combination") if isinstance(sample.get("transition_combination"), dict) else {}
    asset = sample.get("asset_analysis") if isinstance(sample.get("asset_analysis"), dict) else {}

    policy = {
        "version": "viral_execution_policy_v1",
        "analysis_id": f"viral:{_stable_hash(report)[:16]}",
        "source_report_version": _text(report.get("version")),
        "selected_hook": _text(_pick(sample, "selected_hook", "hook", "opening_hook")),
        "content_promise": _text(_pick(sample, "content_promise", "promise", "topic_direction")),
        "narrative_engine": _text(_pick(sample, "narrative_engine", "story_engine", "content_form")),
        "evidence_sequence": _list(_pick(sample, "evidence_sequence", "proof_sequence", "content_structure")),
        "writing_style": style if isinstance(style, (str, list, dict)) else _text(style),
        "visual_mode": _text(_pick(sample, "visual_mode", "visual_form", "content_form")),
        "motion_function": _list(_pick(motion, "function", "functions", "moves", "motion")),
        "transition_semantics": _list(_pick(transition, "semantics", "meaning", "transitions")),
        "anti_template_constraints": [
            "不得回退到标题加方块正文加底部字幕的默认骨架",
            "画面必须新增可解释信息，不能只换颜色、背景或动画名",
            "每个镜头必须兑现一个具体内容动作或证据",
        ],
        "reference_ids": _list(_pick(sample, "reference_ids", "ids")),
        "asset_strategy": asset,
        "topic_direction": _text(sample.get("topic_direction")),
        "eligibility_state": eligibility["state"],
    }
    if not policy["selected_hook"]:
        policy["selected_hook"] = "从参考样本提取首屏冲突，并在前3秒兑现"
    if not policy["evidence_sequence"]:
        policy["evidence_sequence"] = ["冲突", "过程", "证据", "结果", "边界"]
    policy["policy_hash"] = _stable_hash(policy)
    return policy


def find_viral_report(value: Any, platform: str = "") -> dict[str, Any] | None:
    """Find the platform report in brief/context without guessing a path."""
    if not isinstance(value, dict):
        return None
    candidates = [value.get("viral_breakdown"), value.get("viral_breakdown_report")]
    matrix = value.get("platform_source_matrix")
    if isinstance(matrix, dict):
        candidates.append(matrix.get("viral_breakdown"))
    nested = value.get("platforms")
    if isinstance(nested, dict):
        candidates.insert(0, nested.get(str(platform).casefold().strip()))
    for candidate in candidates:
        if isinstance(candidate, dict):
            if "platforms" in candidate and isinstance(candidate["platforms"], dict):
                candidate = candidate["platforms"].get(str(platform).casefold().strip())
            if isinstance(candidate, dict) and candidate.get("status"):
                return candidate
    return None
