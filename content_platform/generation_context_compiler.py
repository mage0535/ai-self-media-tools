"""Compile a small, platform-specific context for a generation provider."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .skill_rule_compiler import select_platform_rules


def _short(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _bounded_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key)[:80]: _bounded_value(item) for key, item in list(value.items())[:8]}
    if isinstance(value, list):
        return [_bounded_value(item) for item in value[:8]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _short(value, 500)


def _selected_rules(brief: dict[str, Any], platform: str) -> list[dict[str, str]]:
    rules = select_platform_rules(((brief.get("compiled_skill_rules") or {}).get("rules") or []), platform)
    result = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        source = str(rule.get("source") or rule.get("id") or "").casefold()
        rule_id = _short(rule.get("rule_id") or rule.get("id"), 180)
        source_id = _short(rule.get("source"), 180)
        text = _short(rule.get("text"), 220)
        identity = json.dumps(
            {"rule_id": rule_id, "source": source_id, "text": " ".join(text.split())},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        result.append({
            "id": rule_id,
            "rule_id": rule_id,
            "source": source_id,
            "text": text,
            "sha256": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        })
    return result


def compile_generation_context(
    *, platform: str, content_format: str, stage: str, brief: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None, retry: bool = False, byte_limit: int | None = None,
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
        "content_blueprint": {str(key)[:80]: _bounded_value(value) for key, value in list(blueprint.items())[:12]},
        "claims": claims,
        "evidence": evidence_summary,
        "selected_capability": [_short(item, 120) for item in capability[:12]] if isinstance(capability, list) else [_short(capability, 120)],
        "selected_rule_ids": _selected_rules(brief, platform),
    }
    limit = max(512, min(int(byte_limit or (8000 if retry else 12000)), 8000 if retry else 12000))
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if _utf8_size(text) > limit:
        payload["content_blueprint"] = {"topic": _short(blueprint.get("topic") or blueprint.get("title"), 240), "content_form": _short(blueprint.get("content_form"), 80)}
        payload["claims"] = claims[:4]
        payload["evidence"]["samples"] = evidence_summary["samples"][:3]
        payload["selected_rule_ids"] = payload["selected_rule_ids"][:12 if not retry else 6]
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if _utf8_size(text) > limit:
            payload["selected_rule_ids"] = []
            payload["claims"] = []
            payload["evidence"]["samples"] = []
            payload["selected_capability"] = []
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        while _utf8_size(text) > limit and payload["content_blueprint"].get("topic"):
            payload["content_blueprint"]["topic"] = payload["content_blueprint"]["topic"][:-16]
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if _utf8_size(text) > limit:
        raise ValueError("generation context cannot fit the UTF-8 byte budget")
    return {
        "text": text,
        "char_count": len(text),
        "byte_count": _utf8_size(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "retry": retry,
    }
