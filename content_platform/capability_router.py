"""Route registry capabilities without claiming unavailable execution."""

from __future__ import annotations

from typing import Any

from .adapter_executor import capability_available
from .capability_catalog import build_capability_catalog, load_capability_registry
from .content_policy import delivery_mode


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
    raw_format = str(profile.get("content_format") or "").casefold()
    aliases = {
        "vertical_video": "short_video",
        "short": "short_video",
        "reel": "short_video",
        "horizontal_video": "long_video",
        "video": "long_video",
        "long_article": "article",
        "short_post": "article",
        "image_text_note": "carousel",
    }
    return aliases.get(raw_format, raw_format) in applies


def match_capabilities(
    profile: dict[str, Any],
    registry: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry or load_registry(str(profile.get("platform") or ""))
    consulted: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    raw_format = str(profile.get("content_format") or "").casefold()
    content_format = {
        "vertical_video": "short_video", "short": "short_video", "reel": "short_video",
        "horizontal_video": "long_video", "video": "long_video",
        "long_article": "article", "image_text_note": "carousel",
        "short_post": "article",
    }.get(raw_format, raw_format)
    applicable_groups = [
        group for group in registry.get("groups", [])
        if content_format in set(group.get("applies_to") or [])
    ]
    required_ids = {
        capability_id
        for group in applicable_groups
        if group.get("required_policy") == "required"
        for capability_id in group.get("candidate_ids") or []
    }
    for capability in registry.get("capabilities", []):
        if not _matches(capability, profile):
            continue
        mode = delivery_mode(str(profile.get("platform") or ""))
        if capability.get("id") == "pipeline_publisher" and (runtime_context or {}).get("dry_run") is True:
            skipped.append({"capability_id": capability["id"], "reason": "dry_run_uses_verified_delivery_boundary"})
            continue
        if capability.get("id") == "pipeline_publisher" and mode == "manual_handoff":
            skipped.append({"capability_id": capability["id"], "reason": "delivery_policy_selects_manual_handoff"})
            continue
        if capability.get("id") == "handoff_package_builder" and mode != "manual_handoff":
            skipped.append({"capability_id": capability["id"], "reason": f"delivery_policy_selects_{mode}"})
            continue
        item = {
            "capability_id": capability["id"],
            "stage": capability.get("stage"),
            "adapter": capability.get("adapter"),
            "output_contract": capability.get("output_contract"),
            "quality_gate": capability.get("quality_gate"),
            "verification_level": capability.get("verification_level", "output_verified"),
            "required_or_optional": "required" if capability["id"] in required_ids else "optional",
        }
        lifecycle = capability.get("lifecycle")
        if lifecycle == "inventory_only":
            disposition = capability.get("inventory_disposition") or {}
            inventory.append(
                {
                    "capability_id": capability["id"],
                    "reason": str(disposition.get("reason") or "inventory_only"),
                    "disposition": str(disposition.get("mode") or "unclassified"),
                }
            )
            continue
        if capability.get("kind") == "methodology" and capability.get("license") == "unverified":
            inventory.append({"capability_id": capability["id"], "reason": "license_unverified"})
            continue
        if capability.get("kind") == "methodology":
            consulted.append({**item, "status": "consulted", "rules_applied": []})
            continue
        if lifecycle not in {"executable", "parent_executed"}:
            inventory.append({"capability_id": capability["id"], "reason": "inventory_only"})
            continue
        if lifecycle == "parent_executed":
            parent_id = str(capability.get("parent_id") or "")
            parent = next((row for row in registry.get("capabilities", []) if row.get("id") == parent_id), None)
            if not parent:
                skipped.append({"capability_id": capability["id"], "reason": "parent_capability_missing"})
                continue
            available, reason = capability_available(parent, dict(runtime_context or {}))
            if not available:
                skipped.append({"capability_id": capability["id"], "reason": reason})
                continue
            existing = next((row for row in candidates if row.get("capability_id") == parent_id), None)
            if existing is None:
                existing = {
                    **item,
                    "capability_id": parent_id,
                    "child_capability_ids": [],
                    "child_telemetry_contracts": {},
                    "adapter": parent.get("adapter"),
                    "output_contract": parent.get("output_contract"),
                    "quality_gate": parent.get("quality_gate"),
                    "verification_level": parent.get("verification_level", "output_verified"),
                    "status": "planned",
                }
                candidates.append(existing)
            child_ids = existing.setdefault("child_capability_ids", [])
            if capability["id"] not in child_ids:
                child_ids.append(capability["id"])
            existing.setdefault("child_telemetry_contracts", {})[capability["id"]] = capability.get("telemetry_contract")
            continue
        probe_inputs = dict(runtime_context or {})
        if capability.get("kind") == "mcp_tool":
            probe_inputs.setdefault("mcp_namespace", capability.get("mcp_namespace"))
            probe_inputs.setdefault("mcp_tool", capability.get("mcp_tool"))
        available, reason = capability_available(capability, probe_inputs)
        if not available:
            skipped.append({"capability_id": capability["id"], "reason": reason})
            continue
        existing = next((row for row in candidates if row.get("capability_id") == capability["id"]), None)
        if existing is None:
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
