"""Compile a small, platform-specific context for a generation provider."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .skill_rule_compiler import select_platform_rules


def _short(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _selected_rules(brief: dict[str, Any], platform: str) -> list[dict[str, str]]:
    rules = select_platform_rules(((brief.get("compiled_skill_rules") or {}).get("rules") or []), platform)
    wanted = str(platform).casefold()
    result = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        source = str(rule.get("source") or rule.get("id") or "").casefold()
        result.append({"id": _short(rule.get("id"), 180), "text": _short(rule.get("text"), 220)})
    return result


def compile_generation_context(
    *, platform: str, content_format: str, stage: str, brief: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None, retry: bool = False,
) -> dict[str, Any]:
    brief = brief or {}
    blueprint = brief.get("content_blueprint") if isinstance(brief.get("content_blueprint"), dict) else {}
    claim_rows = brief.get("claim_ledger") or []
    claims = []
    for row in claim_rows[:12] if isinstance(claim_rows, list) else []:
        if isinstance(row, dict):
            claims.append({"claim": _short(row.get("claim"), 240), "evidence": _short(row.get("evidence_path") or row.get("source") or "", 180)})
    evidence = brief.get("evidence_summary") or brief.get("trend_evidence") or {}
    evidence_summary = {
        "source": _short(evidence.get("source") if isinstance(evidence, dict) else "", 180),
        "samples": [_short((item.get("title") or item.get("url") or item.get("source") or ""), 180) for item in (evidence.get("samples") or [])[:6]] if isinstance(evidence, dict) else [],
    }
    capability = brief.get("selected_capability") or ((brief.get("capability_plan") or {}).get("executed") or [])
    payload = {
        "platform": _short(platform, 40),
        "content_format": _short(content_format, 80),
        "stage": _short(stage, 40),
        "content_blueprint": {key: _short(value, 500) if not isinstance(value, (list, dict, bool, int, float)) else value for key, value in list(blueprint.items())[:12]},
        "claims": claims,
        "evidence": evidence_summary,
        "selected_capability": [_short(item, 120) for item in capability[:12]] if isinstance(capability, list) else [_short(capability, 120)],
        "selected_rule_ids": _selected_rules(brief, platform),
    }
    limit = 8000 if retry else 12000
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) > limit:
        payload["content_blueprint"] = {"topic": _short(blueprint.get("topic") or blueprint.get("title"), 240), "content_form": _short(blueprint.get("content_form"), 80)}
        payload["claims"] = claims[:4]
        payload["evidence"]["samples"] = evidence_summary["samples"][:3]
        payload["selected_rule_ids"] = payload["selected_rule_ids"][:12 if not retry else 6]
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text) > limit:
            payload["selected_rule_ids"] = []
            payload["claims"] = []
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {"text": text, "char_count": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "retry": retry}
