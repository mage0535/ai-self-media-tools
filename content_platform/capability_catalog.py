"""Build a single, truthful inventory of content-production capabilities.

Inventory-only entries are discoverable for planning but cannot be selected as
executed capabilities until an allowlisted adapter and gate are registered.
"""

from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = (
    "id", "source", "capability_kind", "lifecycle", "stage", "applies_to",
    "required_inputs", "availability_probe", "adapter", "output_contract",
    "quality_gate", "fallback_chain", "license",
)

_GROUP_STAGE = {
    "ops_strategy": "blueprint",
    "trend_collection": "collection",
    "account_data": "collection",
    "topic_dedup": "selection",
    "article_recipe": "generation",
    "image_text_card_recipe": "generation",
    "knowledge_card": "generation",
    "image_generation": "assets",
    "image_retrieval": "assets",
    "image_editing": "assets",
    "seo_geo": "generation",
    "visual_recipe": "blueprint",
    "source_material": "collection",
    "video_template": "render",
    "motion_effects": "render",
    "transitions": "render",
    "tts": "assets",
    "subtitles": "render",
    "bgm": "assets",
    "audio_mix": "render",
    "quality_gate": "gate",
    "publisher_or_handoff": "delivery",
}


def _entry(
    capability_id: str,
    *,
    source: str,
    kind: str,
    lifecycle: str,
    stage: str,
    applies_to: list[str] | None = None,
    adapter: str = "",
    quality_gate: str = "",
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "source": source,
        "capability_kind": kind,
        "lifecycle": lifecycle,
        "stage": stage,
        "applies_to": applies_to or ["article", "carousel", "short_video", "long_video"],
        "required_inputs": ["content_profile", "content_blueprint"],
        "availability_probe": f"runtime:{capability_id}",
        "adapter": adapter or f"inventory:{capability_id}",
        "output_contract": "capability_result_v1",
        "quality_gate": quality_gate or "artifact_lineage_v1",
        "fallback_chain": [],
        "license": "internal",
    }


def build_capability_catalog(
    registry: dict[str, Any] | None,
    *,
    legacy_groups: dict[str, list[str]] | None = None,
    mcp_servers: list[str] | None = None,
    skill_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Merge executable definitions with truthful inventory-only records."""
    items: dict[str, dict[str, Any]] = {}
    for raw in (registry or {}).get("capabilities", []):
        if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
            continue
        item = dict(raw)
        item.setdefault("source", "project_registry")
        item.setdefault("lifecycle", "executable" if item.get("adapter") else "inventory_only")
        item.setdefault("availability_probe", f"runtime:{item['id']}")
        item.setdefault("quality_gate", "artifact_lineage_v1")
        item.setdefault("fallback_chain", [])
        items[item["id"]] = item

    for group, candidates in (legacy_groups or {}).items():
        for candidate in candidates or []:
            capability_id = str(candidate).strip()
            if not capability_id or capability_id in items:
                continue
            items[capability_id] = _entry(
                capability_id,
                source=f"legacy_tool_group:{group}",
                kind="tool",
                lifecycle="inventory_only",
                stage=_GROUP_STAGE.get(group, "generation"),
            )

    for server in mcp_servers or []:
        capability_id = f"mcp:{str(server).strip()}"
        if capability_id == "mcp:" or capability_id in items:
            continue
        items[capability_id] = _entry(
            capability_id,
            source="mcp",
            kind="mcp_tool_namespace",
            lifecycle="inventory_only",
            stage="collection",
        )

    for path in skill_paths or []:
        normalized = str(path).replace("\\", "/").strip("/")
        parts = set(normalized.casefold().split("/"))
        if not normalized or parts.intersection({".archive", "_archive", "archive"}):
            continue
        capability_id = f"skill:{normalized.removesuffix('/SKILL.md')}"
        if capability_id in items:
            continue
        items[capability_id] = _entry(
            capability_id,
            source="hermes_skill",
            kind="methodology",
            lifecycle="inventory_only",
            stage="blueprint",
            adapter="builtin:reference_compiler",
        )

    return {
        "version": "capability_catalog_v1",
        "capabilities": sorted(items.values(), key=lambda item: item["id"]),
    }


def validate_capability_catalog(catalog: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    items = (catalog or {}).get("capabilities") if isinstance(catalog, dict) else None
    if not isinstance(items, list) or not items:
        return {"passed": False, "failures": ["capabilities_missing"]}
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            failures.append("capability_not_object")
            continue
        capability_id = str(item.get("id") or "").strip()
        if not capability_id:
            failures.append("capability_id_missing")
            continue
        if capability_id in seen:
            failures.append(f"{capability_id}.duplicate")
        seen.add(capability_id)
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if field != "fallback_chain" and value in (None, "", []):
                failures.append(f"{capability_id}.{field}_missing")
        if item.get("lifecycle") == "executable":
            if not str(item.get("adapter") or "").strip():
                failures.append(f"{capability_id}.adapter_missing")
            if not str(item.get("quality_gate") or "").strip():
                failures.append(f"{capability_id}.quality_gate_missing")
    return {"passed": not failures, "failures": failures}
