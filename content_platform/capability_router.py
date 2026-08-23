"""Select capabilities before generation; execution is handled separately."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "creative_capability_registry.json"


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _matches(cap: dict, profile: dict) -> bool:
    applies = set(cap.get("applies_to") or [])
    if profile.get("content_format") in applies:
        return True
    trigger = cap.get("trigger") or {}
    return any(profile.get(axis) in values for axis, values in trigger.items())


def match_capabilities(profile: dict, registry: dict | None = None) -> dict:
    consulted, candidates, skipped = [], [], []
    for cap in (registry or load_registry()).get("capabilities", []):
        if not _matches(cap, profile):
            continue
        if cap.get("license") in {"unverified", ""}:
            skipped.append({"capability_id": cap.get("id"), "reason": "license_unverified"})
            continue
        item = {"capability_id": cap["id"], "stage": cap.get("stage"), "adapter": cap.get("adapter"), "output_contract": cap.get("output_contract")}
        if cap.get("capability_kind") == "methodology":
            consulted.append({**item, "status": "consulted", "rules_applied": list((cap.get("trigger") or {}).keys())})
        else:
            candidates.append(item)
    return {"consulted": consulted, "candidates": candidates, "executed": [], "skipped": skipped}


def build_capability_plan(profile: dict, registry: dict | None = None) -> dict:
    result = match_capabilities(profile, registry)
    return {"version": "capability_plan_v1", "profile": profile, **result}


def build_invocation_manifest(match_result: dict) -> dict:
    """Backward-compatible selection manifest; execution is added by the executor."""
    return {
        "version": "capability_invocation_v2",
        "consulted_capabilities": match_result.get("consulted", []),
        "selected_capabilities": match_result.get("candidates", []),
        "executed_capabilities": match_result.get("executed", []),
        "skipped_capabilities": match_result.get("skipped", []),
        "generated_assets": [],
        "quality_gates": [],
    }
