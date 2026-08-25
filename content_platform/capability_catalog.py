"""Load and validate the creative capability registry.

The JSON registry is the only source for legacy groups and capability records.
This module deliberately does not synthesize Skill, MCP, or legacy entries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "creative_capability_registry.json"
REQUIRED_CAPABILITY_FIELDS = (
    "id",
    "source",
    "kind",
    "lifecycle",
    "stage",
    "applies_to",
    "required_inputs",
    "availability_probe",
    "adapter",
    "output_contract",
    "quality_gate",
    "fallback_chain",
    "license",
)


def validate_capability_registry(registry: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(registry, dict):
        return {"passed": False, "failures": ["registry_not_object"]}

    groups = registry.get("groups")
    capabilities = registry.get("capabilities")
    if not isinstance(groups, list) or not groups:
        failures.append("groups_missing")
        groups = []
    if not isinstance(capabilities, list) or not capabilities:
        failures.append("capabilities_missing")
        capabilities = []
    if len(groups) != 22:
        failures.append(f"group_coverage_count:{len(groups)}")

    group_ids: set[str] = set()
    referenced_ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            failures.append("group_not_object")
            continue
        group_id = str(group.get("id") or "").strip()
        if not group_id:
            failures.append("group_id_missing")
            continue
        if group_id in group_ids:
            failures.append(f"group_duplicate:{group_id}")
        group_ids.add(group_id)
        if not isinstance(group.get("applies_to"), list) or not group["applies_to"]:
            failures.append(f"{group_id}.applies_to_missing")
        if group.get("required_policy") not in {"required", "optional"}:
            failures.append(f"{group_id}.required_policy_missing")
        candidate_ids = group.get("candidate_ids")
        if not isinstance(candidate_ids, list) or not candidate_ids:
            failures.append(f"{group_id}.candidate_ids_missing")
            continue
        if any(not isinstance(item, str) or not item.strip() for item in candidate_ids):
            failures.append(f"{group_id}.candidate_id_invalid")
        referenced_ids.extend(str(item).strip() for item in candidate_ids if str(item).strip())

    if len(referenced_ids) != 48:
        failures.append(f"candidate_appearance_count:{len(referenced_ids)}")
    if len(set(referenced_ids)) != 47:
        failures.append(f"candidate_unique_count:{len(set(referenced_ids))}")

    capability_ids: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, dict):
            failures.append("capability_not_object")
            continue
        capability_id = str(capability.get("id") or "").strip()
        if not capability_id:
            failures.append("capability_id_missing")
            continue
        if capability_id in capability_ids:
            failures.append(f"{capability_id}.duplicate")
        capability_ids.add(capability_id)
        for field in REQUIRED_CAPABILITY_FIELDS:
            if field not in capability:
                failures.append(f"{capability_id}.{field}_missing")
        if not isinstance(capability.get("applies_to"), list) or not capability["applies_to"]:
            failures.append(f"{capability_id}.applies_to_missing")
        if not isinstance(capability.get("required_inputs"), list):
            failures.append(f"{capability_id}.required_inputs_invalid")
        if not isinstance(capability.get("fallback_chain"), list):
            failures.append(f"{capability_id}.fallback_chain_invalid")
        if capability.get("lifecycle") == "executable":
            adapter = str(capability.get("adapter") or "")
            if not adapter:
                failures.append(f"{capability_id}.adapter_missing")
            else:
                from .adapter_executor import supported_adapter_targets

                if adapter not in supported_adapter_targets():
                    failures.append(f"{capability_id}.adapter_not_supported")
            if not str(capability.get("availability_probe") or ""):
                failures.append(f"{capability_id}.availability_probe_missing")
            if not str(capability.get("output_contract") or ""):
                failures.append(f"{capability_id}.output_contract_missing")
            if not str(capability.get("quality_gate") or ""):
                failures.append(f"{capability_id}.quality_gate_missing")
            if not str(capability.get("runtime_evidence") or ""):
                failures.append(f"{capability_id}.runtime_evidence_missing")
            if "fallback_chain" not in capability:
                failures.append(f"{capability_id}.fallback_chain_missing")

    for capability_id in sorted(set(referenced_ids) - capability_ids):
        failures.append(f"group_orphan_reference:{capability_id}")
    return {"passed": not failures, "failures": failures}


def load_capability_registry(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = Path(path) if path else DEFAULT_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    result = validate_capability_registry(registry)
    if not result["passed"]:
        raise ValueError("invalid capability registry: " + ";".join(result["failures"]))
    return registry


def build_capability_catalog(
    registry: dict[str, Any],
    *,
    legacy_groups: dict[str, list[str]] | None = None,
    mcp_servers: list[str] | None = None,
    skill_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Return the validated registry without merging a second inventory."""
    del legacy_groups, mcp_servers, skill_paths
    result = validate_capability_registry(registry)
    if not result["passed"]:
        raise ValueError("invalid capability registry: " + ";".join(result["failures"]))
    return {
        "version": "capability_catalog_v2",
        "groups": [dict(group) for group in registry["groups"]],
        "capabilities": [dict(capability) for capability in registry["capabilities"]],
    }


def validate_capability_catalog(catalog: dict[str, Any] | None) -> dict[str, Any]:
    """Backward-compatible validator for callers using the old name."""
    return validate_capability_registry(catalog)
