"""Sanitized runtime capability evidence for content planning.

The snapshot intentionally contains availability and stable identifiers only.
Absolute paths, endpoints, cookies, provider errors, and credentials must not
enter model input or publishable run evidence.
"""

from __future__ import annotations

from typing import Any

from .tool_registry import ToolRegistry
from .video_recipe import load_effect_module_registry


_SAFE_FIELDS = {
    "available", "kind", "daemon", "autocli_ok", "fusion_script_ok",
    "chrome_ext_ok", "total_skills", "skill_count",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict):
        return {"available": bool(value)}
    return {key: value[key] for key in _SAFE_FIELDS if key in value and isinstance(value[key], (bool, int, str))}


def build_runtime_capability_snapshot() -> dict[str, Any]:
    """Return the currently available project capabilities without private data."""
    probed = ToolRegistry({"fast_probe": True}).probe()
    tools = {str(name): _sanitize(record) for name, record in probed.items()}
    registry = load_effect_module_registry()
    modules = registry.get("modules") if isinstance(registry, dict) else {}
    families = registry.get("template_families") if isinstance(registry, dict) else {}
    return {
        "version": "runtime_capabilities_v1",
        "tools": tools,
        "available_tools": sorted(name for name, record in tools.items() if record.get("available") is True),
        "video_effect_modules": {
            "version": str(registry.get("version") or "") if isinstance(registry, dict) else "",
            "modules": {str(name): {"available": True} for name in modules} if isinstance(modules, dict) else {},
            "template_families": {str(name): {"available": True} for name in families} if isinstance(families, dict) else {},
        },
    }
