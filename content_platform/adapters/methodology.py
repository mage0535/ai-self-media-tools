"""Compile selected skill references into consulted-only evidence."""

from __future__ import annotations

from typing import Any

from ..skill_rule_compiler import select_platform_rules


def execute(inputs: dict[str, Any]) -> dict[str, Any]:
    compiled = inputs.get("compiled_skill_rules") or {}
    platform = str(inputs.get("platform") or "")
    rules = [
        rule for rule in select_platform_rules(list(compiled.get("rules") or []), platform)
        if isinstance(rule, dict) and str(rule.get("id") or "").strip()
    ]
    rule_ids = sorted({str(rule["id"]) for rule in rules})
    rule_sources = {
        str(rule["id"]): str(rule.get("source") or "").strip()
        for rule in rules
    }
    source_hashes = {
        str(source.get("id")): str(source.get("sha256")).strip()
        for source in (compiled.get("sources") or [])
        if isinstance(source, dict) and str(source.get("id") or "").strip() and str(source.get("sha256") or "").strip()
    }
    selected_sources = set(rule_sources.values())
    source_hashes = {key: source_hashes[key] for key in sorted(source_hashes) if key in selected_sources}
    affected = inputs.get("affected_outputs") or ["generation_context"]
    unknown_sources = [
        rule_id for rule_id in rule_ids
        if not rule_sources.get(rule_id) or not source_hashes.get(rule_sources[rule_id])
    ]
    return {
        "version": "reference_compilation_v1",
        "rule_ids": rule_ids,
        "rule_sources": rule_sources,
        "source_hashes": source_hashes,
        "rules_applied": rule_ids,
        "affected_outputs": sorted({str(item) for item in affected if str(item).strip()}),
        **({"status": "failed", "reason": "unknown_rule_source:" + ",".join(unknown_sources)} if unknown_sources else {}),
    }
