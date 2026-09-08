from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "platform_intelligence_registry.json"


def load_platform_intelligence_registry(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path else REGISTRY_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    failures = validate_platform_intelligence_registry(payload)
    if failures:
        raise ValueError("invalid platform intelligence registry: " + ",".join(failures))
    return payload


def validate_platform_intelligence_registry(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return ["registry_not_object"]
    failures: list[str] = []
    targets = payload.get("publish_targets")
    references = payload.get("reference_sources")
    if not isinstance(targets, dict) or not targets:
        failures.append("publish_targets_missing")
    if not isinstance(references, dict) or not references:
        failures.append("reference_sources_missing")
    for name, row in (targets or {}).items():
        if not isinstance(row, dict) or not row.get("collectors") or not row.get("default_queries"):
            failures.append(f"publish_target_invalid:{name}")
    for name, row in (references or {}).items():
        if not isinstance(row, dict) or not row.get("adapter") or row.get("identity_role") != "cross_platform_reference":
            failures.append(f"reference_source_invalid:{name}")
    return failures


def publishing_platforms() -> list[str]:
    return list(load_platform_intelligence_registry()["publish_targets"])


def platform_queries(platform: str) -> list[str]:
    row = load_platform_intelligence_registry()["publish_targets"].get(str(platform or "").casefold(), {})
    return [str(value) for value in row.get("default_queries") or []]


def reference_source_configs() -> dict[str, dict[str, Any]]:
    rows = load_platform_intelligence_registry()["reference_sources"]
    return {name: dict(row) for name, row in rows.items() if row.get("enabled") is True}


__all__ = [
    "load_platform_intelligence_registry",
    "platform_queries",
    "publishing_platforms",
    "reference_source_configs",
    "validate_platform_intelligence_registry",
]
