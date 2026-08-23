"""Execute generation-stage capabilities and produce fail-closed evidence."""

from __future__ import annotations

from .adapter_executor import execute_capability
from .capability_router import load_registry, match_capabilities
from .content_profile import classify_content_profile
from .execution_dag import execute_capability_dag


def execute_generation_capabilities(draft: dict, brief: dict | None = None) -> dict:
    brief = brief or {}
    profile = brief.get("content_profile") or classify_content_profile(
        f"{draft.get('title', '')} {draft.get('body', '')}",
        platform=str(brief.get("platform") or ""),
        content_format=str(brief.get("content_form") or "article"),
    )
    registry = load_registry()
    matched = match_capabilities(profile, registry)
    def executor(item, current_draft, current_brief):
        capability = next(c for c in registry["capabilities"] if c["id"] == item["capability_id"])
        return execute_capability(capability, {"segments": [current_draft.get("title", ""), current_draft.get("body", "")]})

    result = execute_capability_dag(matched, draft, brief, executor=executor)
    result["profile"] = profile
    result["skipped"] = matched.get("skipped", [])
    result["inventory"] = matched.get("inventory", [])
    return result
