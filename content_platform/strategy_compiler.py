"""Compile human-readable growth strategy into bounded generation policy."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


STRUCTURE_POOL = [
    "pain_reversal_tutorial",
    "real_demo_before_after",
    "failure_postmortem",
    "controversial_viewpoint",
    "saveable_checklist",
    "story_microcase",
]
CTA_POOL = ["specific_open_question", "identity_question", "choice_question", "save_reason"]


def compile_strategy(path: str | Path, platform: str) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    normalized = str(platform or "").casefold()
    if "�" in text:
        raise ValueError("growth strategy contains mojibake")
    content_pillars = _extract_pillars(text)
    hook_templates = _extract_quoted(text, limit=8)
    kpis = _extract_kpis(text)
    strategy = {
        "version": "compiled_strategy_v1",
        "platform": normalized,
        "source_path": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "content_pillars": content_pillars or ["practical problem solving", "evidence-backed workflow", "saveable checklist"],
        "structure_pool": STRUCTURE_POOL,
        "hook_templates": hook_templates,
        "cta_pool": CTA_POOL,
        "kpi_hypotheses": kpis,
        "evidence_policy": {
            "numeric_claim_requires_source": True,
            "first_person_operation_requires_evidence": True,
            "strategy_claims_are_hypotheses_until_metrics_eligible": True,
        },
        "selection_policy": {
            "same_core_topic_same_day": "block",
            "cross_platform_resonance": "allow_only_with_different_angle_form_evidence",
            "shadow_can_report": True,
            "shadow_can_create_jobs": False,
        },
    }
    return strategy


def _extract_pillars(text: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [re.sub(r"[*#`]+", "", item).strip() for item in line.split("|")]
        if len(cells) >= 3 and any(token in " ".join(cells).casefold() for token in ("解决", "避坑", "对比", "教程", "效率", "痛点")):
            candidate = cells[1] or cells[0]
            if candidate and candidate not in values and not set(candidate) <= {"-", ":"}:
                values.append(candidate)
    return values[:8]


def _extract_quoted(text: str, limit: int) -> list[str]:
    values = re.findall(r"[「『“\"]([^」』”\"]{6,80})[」』”\"]", text)
    return list(dict.fromkeys(item.strip() for item in values))[:limit]


def _extract_kpis(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("5s完播率", "2s跳出率", "评论率", "点赞率", "收藏率", "完播率"):
        match = re.search(re.escape(key) + r"[^\n|]{0,40}?([<>≥≤]?\s*\d+(?:\.\d+)?%)", text, re.I)
        if match:
            result[key] = match.group(1).replace(" ", "")
    return result


def validate_compiled_strategy(strategy: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(strategy, dict):
        return {"passed": False, "failures": ["compiled_strategy_missing"]}
    for field in ("version", "platform", "source_sha256", "content_pillars", "structure_pool", "cta_pool", "evidence_policy"):
        if not strategy.get(field):
            failures.append(f"compiled_strategy_{field}_missing")
    if len(strategy.get("structure_pool") or []) < 5:
        failures.append("compiled_strategy_structure_pool_too_small")
    if strategy.get("selection_policy", {}).get("shadow_can_create_jobs") is not False:
        failures.append("compiled_strategy_shadow_publish_boundary_invalid")
    return {"passed": not failures, "failures": failures}


def compact_compiled_strategy(strategy: dict[str, Any] | None) -> dict[str, Any]:
    """Keep provider policy bounded while retaining auditable provenance."""
    if not isinstance(strategy, dict):
        return {}
    fields = (
        "version", "platform", "source_sha256", "content_pillars", "structure_pool",
        "hook_templates", "cta_pool", "kpi_hypotheses", "evidence_policy", "selection_policy",
    )
    def clip(value: Any) -> Any:
        if isinstance(value, str):
            return value[:180]
        if isinstance(value, list):
            return [clip(item) for item in value[:6]]
        if isinstance(value, dict):
            return {str(key): clip(item) for key, item in list(value.items())[:8]}
        return value

    compact = {key: clip(strategy[key]) for key in fields if key in strategy}
    encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 5000:
        compact = {
            key: clip(strategy[key])
            for key in ("version", "platform", "source_sha256", "content_pillars", "structure_pool", "hook_templates", "cta_pool", "selection_policy")
            if key in strategy
        }
        for key in ("content_pillars", "structure_pool", "hook_templates", "cta_pool"):
            if isinstance(compact.get(key), list):
                compact[key] = [str(item)[:100] for item in compact[key][:3]]
    return compact
