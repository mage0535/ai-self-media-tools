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
    # Preserve nested provider availability in a safe, model-readable shape.
    # The old generic sanitizer turned ``tts_engines`` into an empty object,
    # so planning could not distinguish an available voice provider from a
    # missing one.
    raw_tts = probed.get("tts_engines")
    if isinstance(raw_tts, dict):
        tools["tts_engines"] = {
            str(name): _sanitize(record)
            for name, record in raw_tts.items()
            if isinstance(record, (dict, bool))
        }
    registry = load_effect_module_registry()
    modules = registry.get("modules") if isinstance(registry, dict) else {}
    families = registry.get("template_families") if isinstance(registry, dict) else {}
    available_tools = sorted(
        name for name, record in tools.items()
        if isinstance(record, dict) and record.get("available") is True
    )
    for name, record in (tools.get("tts_engines") or {}).items():
        if isinstance(record, dict) and record.get("available") is True:
            available_tools.append(f"tts_engines.{name}")
    return {
        "version": "runtime_capabilities_v1",
        "tools": tools,
        "available_tools": sorted(set(available_tools)),
        "video_effect_modules": {
            "version": str(registry.get("version") or "") if isinstance(registry, dict) else "",
            "modules": {str(name): {"available": True} for name in modules} if isinstance(modules, dict) else {},
            "template_families": {str(name): {"available": True} for name in families} if isinstance(families, dict) else {},
        },
    }


def compact_runtime_capability_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Keep model input bounded while retaining every executable identifier."""
    snapshot = snapshot or {}
    effects = snapshot.get("video_effect_modules") if isinstance(snapshot.get("video_effect_modules"), dict) else {}
    modules = effects.get("modules") if isinstance(effects.get("modules"), dict) else {}
    families = effects.get("template_families") if isinstance(effects.get("template_families"), dict) else {}
    return {
        "version": snapshot.get("version", "runtime_capabilities_v1"),
        "available_tools": sorted(str(item) for item in (snapshot.get("available_tools") or [])),
        "video_effect_modules": {
            "version": effects.get("version", ""),
            "module_ids": sorted(str(item) for item in modules),
            "template_family_ids": sorted(str(item) for item in families),
        },
    }
