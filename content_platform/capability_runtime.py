"""Execute generation-stage capabilities and produce fail-closed evidence."""

from __future__ import annotations

from .adapter_executor import execute_capability
from .capability_router import load_registry, match_capabilities
from .content_profile import classify_content_profile


def execute_generation_capabilities(draft: dict, brief: dict | None = None) -> dict:
    brief = brief or {}
    profile = brief.get("content_profile") or classify_content_profile(
        f"{draft.get('title', '')} {draft.get('body', '')}",
        platform=str(brief.get("platform") or ""),
        content_format=str(brief.get("content_form") or "article"),
    )
    registry = load_registry()
    matched = match_capabilities(profile, registry)
    executed = []
    failures = []
    for item in matched.get("candidates", []):
        capability = next(c for c in registry["capabilities"] if c["id"] == item["capability_id"])
        result = execute_capability(capability, {"segments": [draft.get("title", ""), draft.get("body", "")]})
        record = {"capability_id": capability["id"], **result}
        if result.get("status") == "executed":
            executed.append(record)
        else:
            failures.append(record)
    return {
        "version": "capability_execution_v1",
        "profile": profile,
        "consulted": matched.get("consulted", []),
        "executed": executed,
        "skipped": matched.get("skipped", []),
        "failures": failures,
        "passed": not failures,
    }
