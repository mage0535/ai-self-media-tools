"""Registry-derived capability analysis and selection contracts."""

from __future__ import annotations

from typing import Any

from .adapter_executor import capability_available
from .capability_catalog import load_capability_registry
from .tool_catalog import catalog_snapshot


def _is_video(content_type: str) -> bool:
    text = str(content_type or "").casefold()
    return "video" in text or text in {"short", "reel"}


def _groups_for_content(content_type: str, registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = registry or load_capability_registry()
    desired = {"short_video", "long_video"} if _is_video(content_type) else {"article", "carousel"}
    return [group for group in registry["groups"] if desired.intersection(group["applies_to"])]


def _group_views(content_type: str) -> dict[str, list[str]]:
    return {group["id"]: list(group["candidate_ids"]) for group in _groups_for_content(content_type)}


# Compatibility constants are views over the registry, not independent facts.
ARTICLE_TOOL_GROUPS = frozenset(_group_views("article"))
VIDEO_TOOL_GROUPS = frozenset(_group_views("video"))


def _capability_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in registry["capabilities"]}


def build_tools_capability_analysis(
    *,
    platform: str,
    content_type: str,
    capability_status: dict[str, Any] | None = None,
    video_effect_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inventory all registry candidates and fail closed for required groups."""
    registry = load_capability_registry()
    groups = _groups_for_content(content_type, registry)
    capabilities = _capability_index(registry)
    status = capability_status if isinstance(capability_status, dict) else {}
    probed = status.get("capabilities") if isinstance(status.get("capabilities"), dict) else {}
    analyzed_groups = {group["id"]: list(group["candidate_ids"]) for group in groups}
    runtime_tools = status.get("tools") if isinstance(status.get("tools"), dict) else {}
    if runtime_tools:
        analyzed_groups["runtime_probe"] = sorted(runtime_tools)
    effect_modules = (video_effect_registry or {}).get("modules") if isinstance(video_effect_registry, dict) else {}
    if isinstance(effect_modules, dict) and effect_modules:
        analyzed_groups["video_effect_modules"] = sorted(effect_modules)
    available: set[str] = set()
    group_status: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for group in groups:
        executable = []
        inventory = []
        for candidate_id in group["candidate_ids"]:
            capability = capabilities[candidate_id]
            if capability.get("lifecycle") != "executable":
                inventory.append(candidate_id)
                continue
            override = probed.get(candidate_id)
            is_available = override.get("available") is True if isinstance(override, dict) else capability_available(capability)[0]
            if is_available:
                executable.append(candidate_id)
                available.add(candidate_id)
        if executable:
            group_status[group["id"]] = {"status": "available", "executable_candidates": executable, "inventory_candidates": inventory}
        elif group["required_policy"] == "required":
            failures.append(f"required_group_no_executable_adapter:{group['id']}")
            group_status[group["id"]] = {"status": "blocked", "executable_candidates": [], "inventory_candidates": inventory}
        else:
            group_status[group["id"]] = {"status": "optional_unavailable", "executable_candidates": [], "inventory_candidates": inventory}
    return {
        "version": "tools_capability_analysis_v2",
        "platform": platform,
        "content_type": content_type,
        "required_tool_groups": [group["id"] for group in groups],
        "analyzed_tool_groups": analyzed_groups,
        "candidate_tool_count": sum(len(items) for items in analyzed_groups.values()),
        "available_tool_ids": sorted(available),
        "group_status": group_status,
        "selection_status": "blocked" if failures else "ready",
        "failures": failures,
        "selection_policy": "select only executable registry capabilities with a confirmed adapter; inventory entries remain visible but are never selected",
        "all_relevant_tool_types_analyzed": True,
        "tool_catalog": catalog_snapshot(),
    }


def build_tool_selection_plan(
    *,
    platform: str,
    content_type: str,
    content_goal: str = "",
    capability_analysis: dict[str, Any] | None = None,
    planned_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select only availability-confirmed executable capabilities."""
    analysis = capability_analysis or build_tools_capability_analysis(platform=platform, content_type=content_type)
    registry = load_capability_registry()
    capabilities = _capability_index(registry)
    aliases = {
        str(alias): capability["id"]
        for capability in registry["capabilities"]
        if capability.get("lifecycle") == "executable"
        for alias in (capability.get("aliases") or [])
        if str(alias).strip()
    }
    available = set(analysis.get("available_tool_ids") or [])
    has_manifest = isinstance(planned_manifest, dict) and "planned_tools" in planned_manifest
    planned_value = planned_manifest.get("planned_tools") if has_manifest else None
    if isinstance(planned_value, dict):
        requested = list(planned_value)
    elif isinstance(planned_value, list):
        requested = [str(item) for item in planned_value]
    else:
        requested = []
    use_manifest = has_manifest
    selected: list[str] = []
    selected_canonical: list[str] = []
    rejected: list[dict[str, str]] = []

    def resolve(name: str) -> str | None:
        canonical = name if name in capabilities else aliases.get(name)
        if not canonical:
            return None
        capability = capabilities.get(canonical)
        if not capability or capability.get("lifecycle") != "executable" or canonical not in available:
            return None
        return canonical

    if use_manifest:
        for name in requested:
            canonical = resolve(name)
            if canonical is None:
                reason = "unknown registry capability or declared alias" if name not in capabilities and name not in aliases else "capability is not an availability-confirmed executable adapter"
                rejected.append({"tool": name, "reason": reason})
                continue
            selected.append(name)
            selected_canonical.append(canonical)
    else:
        for group_id in analysis.get("required_tool_groups") or []:
            candidates = ((analysis.get("group_status") or {}).get(group_id) or {}).get("executable_candidates") or []
            for candidate in candidates:
                canonical = resolve(str(candidate))
                if canonical is None or canonical in selected_canonical:
                    continue
                selected.append(canonical)
                selected_canonical.append(canonical)
                break
    failures = list(analysis.get("failures") or [])
    selection_status = "blocked" if failures else ("ready" if selected else "empty")
    return {
        "version": "tool_selection_plan_v2",
        "platform": platform,
        "content_type": content_type,
        "content_goal": content_goal or "improve retention, saves, interaction, and follow conversion",
        "candidate_group_count": len(analysis.get("required_tool_groups") or []),
        "selected_tools": selected,
        "rejected_tools": rejected,
        "selection_status": selection_status,
        "failures": failures,
        "selection_reasons": {
            name: (
                "selected because the registry adapter probe confirmed executable availability"
                if name == canonical
                else f"selected as declared alias for registry capability {canonical}"
            )
            for name, canonical in zip(selected, selected_canonical)
        },
        "unselected_tools": [
            {"tool_group": group, "reason": "no executable registry candidate is available for this group"}
            for group in analysis.get("required_tool_groups") or []
            if not any(
                resolve(str(name)) in selected_canonical
                for name in (analysis.get("analyzed_tool_groups") or {}).get(group, [])
            )
        ],
        "invocation_order": selected,
        "fallback_plan": "record failure and follow the registry fallback_chain; never promote inventory-only candidates",
        "not_default_only": True,
        "resolved_capability_ids": selected_canonical,
    }


def build_tool_selection_evidence(
    *,
    platform: str,
    content_type: str,
    content_goal: str = "",
    capability_status: dict[str, Any] | None = None,
    video_effect_registry: dict[str, Any] | None = None,
    planned_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = build_tools_capability_analysis(
        platform=platform,
        content_type=content_type,
        capability_status=capability_status,
        video_effect_registry=video_effect_registry,
    )
    return {
        "tools_capability_analysis": analysis,
        "tool_selection_plan": build_tool_selection_plan(
            platform=platform,
            content_type=content_type,
            content_goal=content_goal,
            capability_analysis=analysis,
            planned_manifest=planned_manifest,
        ),
    }


def validate_tool_selection_evidence(packet: dict[str, Any] | None, *, content_kind: str = "") -> dict[str, Any]:
    packet = packet or {}
    content_type = str(packet.get("content_type") or packet.get("content_form") or content_kind)
    analysis = packet.get("tools_capability_analysis") if isinstance(packet.get("tools_capability_analysis"), dict) else {}
    plan = packet.get("tool_selection_plan") if isinstance(packet.get("tool_selection_plan"), dict) else {}
    failures: list[str] = []
    if not analysis:
        failures.append("tools_capability_analysis missing")
    else:
        required = set(analysis.get("required_tool_groups") or [])
        analyzed = set((analysis.get("analyzed_tool_groups") or {}).keys())
        for group in sorted(required - analyzed):
            failures.append("tools_capability_analysis missing groups:" + group)
        if analysis.get("all_relevant_tool_types_analyzed") is not True:
            failures.append("tools_capability_analysis must mark all relevant tool types analyzed")
        failures.extend(str(item) for item in analysis.get("failures") or [])
    if not plan:
        failures.append("tool_selection_plan missing")
    else:
        selected = [str(item) for item in plan.get("selected_tools") or [] if str(item).strip()]
        if plan.get("selection_status") == "blocked":
            failures.extend(str(item) for item in plan.get("failures") or [])
        elif not selected:
            failures.append("tool_selection_plan selected_tools missing")
        if not plan.get("selection_reasons") and selected:
            failures.append("tool_selection_plan selection reasons missing")
        if not plan.get("invocation_order") and selected:
            failures.append("tool_selection_plan invocation order missing")
        if plan.get("not_default_only") is not True:
            failures.append("tool_selection_plan must reject default-only path")
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["tool_selection"] if failures else []}
