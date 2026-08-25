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
    source_hashes = {
        str(source.get("id")): str(source.get("sha256"))
        for source in (compiled.get("sources") or [])
        if isinstance(source, dict) and source.get("id") and source.get("sha256")
    }
    selected_sources = {str(rule.get("source") or "") for rule in rules}
    source_hashes = {key: source_hashes[key] for key in sorted(source_hashes) if key in selected_sources}
    affected = inputs.get("affected_outputs") or ["generation_context"]
    return {
        "version": "reference_compilation_v1",
        "rule_ids": rule_ids,
        "source_hashes": source_hashes,
        "rules_applied": rule_ids,
        "affected_outputs": sorted({str(item) for item in affected if str(item).strip()}),
    }
