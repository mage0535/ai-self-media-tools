"""Select capabilities before generation; execution is handled separately."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .capability_catalog import build_capability_catalog

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "creative_capability_registry.json"


def _runtime_mcp_servers() -> list[str]:
    configured = [item.strip() for item in os.environ.get("CONTENT_PLATFORM_MCP_SERVERS", "").split(",") if item.strip()]
    if configured:
        return configured
    config = Path.home() / ".hermes" / "config.yaml"
    if not config.is_file():
        return []
    try:
        import yaml
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        servers = data.get("mcp_servers") or data.get("mcp") or {}
        return sorted(str(name) for name, value in servers.items() if isinstance(value, dict) and value.get("enabled") is True)
    except Exception:
        return []


def legacy_tool_group_plan(content_type: str) -> dict:
    """Expose legacy tool candidates in the unified plan without claiming execution."""
    from .tool_selection import ARTICLE_TOOL_GROUPS, VIDEO_TOOL_GROUPS, _default_candidates, _is_video
    is_video = _is_video(content_type)
    groups = VIDEO_TOOL_GROUPS if is_video else ARTICLE_TOOL_GROUPS
    return {group: _default_candidates(group, is_video) for group in sorted(groups)}


def load_registry(platform: str = "") -> dict:
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    from .skill_rule_compiler import default_skill_paths

    skills = [str(path) for path in default_skill_paths(platform, root=ROOT)]
    mcp_servers = _runtime_mcp_servers()
    return build_capability_catalog(
        raw,
        legacy_groups=legacy_tool_group_plan("short_video") | legacy_tool_group_plan("article"),
        mcp_servers=mcp_servers,
        skill_paths=skills,
    )


def _matches(cap: dict, profile: dict) -> bool:
    applies = set(cap.get("applies_to") or [])
    if profile.get("content_format") in applies:
        return True
    trigger = cap.get("trigger") or {}
    return any(profile.get(axis) in values for axis, values in trigger.items())


def match_capabilities(profile: dict, registry: dict | None = None) -> dict:
    consulted, candidates, skipped, inventory = [], [], [], []
    for cap in (registry or load_registry()).get("capabilities", []):
        if not _matches(cap, profile):
            continue
        if cap.get("lifecycle") == "inventory_only":
            inventory.append({"capability_id": cap.get("id"), "reason": "adapter_not_registered"})
            continue
        if cap.get("license") in {"unverified", ""}:
            skipped.append({"capability_id": cap.get("id"), "reason": "license_unverified"})
            continue
        item = {
            "capability_id": cap["id"],
            "stage": cap.get("stage"),
            "adapter": cap.get("adapter"),
            "output_contract": cap.get("output_contract"),
            "required_or_optional": cap.get("required_or_optional", "required"),
        }
        if cap.get("capability_kind") == "methodology":
            consulted.append({**item, "status": "consulted", "rules_applied": list((cap.get("trigger") or {}).keys())})
        else:
            candidates.append(item)
    return {"consulted": consulted, "candidates": candidates, "executed": [], "skipped": skipped, "inventory": inventory}


def build_capability_plan(profile: dict, registry: dict | None = None) -> dict:
    result = match_capabilities(profile, registry or load_registry(str(profile.get("platform") or "")))
    return {
        "version": "capability_plan_v2",
        "profile": profile,
        "tool_groups": legacy_tool_group_plan(str(profile.get("content_format") or "article")),
        **result,
    }


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
