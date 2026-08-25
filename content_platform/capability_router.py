"""Route registry capabilities without claiming unavailable execution."""

from __future__ import annotations

from typing import Any

from .adapter_executor import capability_available
from .capability_catalog import build_capability_catalog, load_capability_registry


def _is_video(content_type: str) -> bool:
    text = str(content_type or "").casefold()
    return "video" in text or text in {"short", "reel"}


def legacy_tool_group_plan(content_type: str) -> dict[str, list[str]]:
    registry = load_capability_registry()
    desired = {"short_video", "long_video"} if _is_video(content_type) else {"article", "carousel"}
    return {
        group["id"]: list(group["candidate_ids"])
        for group in registry["groups"]
        if desired.intersection(group["applies_to"])
    }


def load_registry(platform: str = "") -> dict[str, Any]:
    del platform
    return build_capability_catalog(load_capability_registry())


def _matches(capability: dict[str, Any], profile: dict[str, Any]) -> bool:
    applies = set(capability.get("applies_to") or [])
    return str(profile.get("content_format") or "") in applies


def match_capabilities(profile: dict[str, Any], registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry(str(profile.get("platform") or ""))
    consulted: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for capability in registry.get("capabilities", []):
        if not _matches(capability, profile):
            continue
        item = {
            "capability_id": capability["id"],
            "stage": capability.get("stage"),
            "adapter": capability.get("adapter"),
            "output_contract": capability.get("output_contract"),
            "quality_gate": capability.get("quality_gate"),
            "required_or_optional": capability.get("required_or_optional", "required"),
        }
        if capability.get("kind") == "methodology":
            consulted.append({**item, "status": "consulted", "rules_applied": []})
            continue
        if capability.get("lifecycle") != "executable":
            inventory.append({"capability_id": capability["id"], "reason": "inventory_only"})
            continue
        available, reason = capability_available(capability)
        if not available:
            skipped.append({"capability_id": capability["id"], "reason": reason})
            continue
        candidates.append({**item, "status": "planned"})

    from .tool_selection import build_tools_capability_analysis

    analysis = build_tools_capability_analysis(
        platform=str(profile.get("platform") or ""),
        content_type=str(profile.get("content_format") or "article"),
    )
    return {
        "consulted": consulted,
        "candidates": candidates,
        "executed": [],
        "skipped": skipped,
        "inventory": inventory,
        "selection_status": analysis["selection_status"],
        "selection_failures": analysis["failures"],
        "group_status": analysis["group_status"],
    }


def build_capability_plan(profile: dict[str, Any], registry: dict[str, Any] | None = None) -> dict[str, Any]:
    result = match_capabilities(profile, registry or load_registry(str(profile.get("platform") or "")))
    return {
        "version": "capability_plan_v3",
        "profile": profile,
        "tool_groups": legacy_tool_group_plan(str(profile.get("content_format") or "article")),
        **result,
    }


def build_invocation_manifest(match_result: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible manifest; execution is added by the runtime DAG."""
    return {
        "version": "capability_invocation_v3",
        "consulted_capabilities": match_result.get("consulted", []),
        "selected_capabilities": match_result.get("candidates", []),
        "executed_capabilities": match_result.get("executed", []),
        "skipped_capabilities": match_result.get("skipped", []),
        "inventory_capabilities": match_result.get("inventory", []),
        "selection_status": match_result.get("selection_status", "blocked"),
        "selection_failures": match_result.get("selection_failures", []),
        "generated_assets": [],
        "quality_gates": [],
    }
