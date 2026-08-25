"""Execute generation-stage capabilities and produce fail-closed evidence."""

from __future__ import annotations

from .adapter_executor import execute_capability
from .capability_router import load_registry, match_capabilities
from .content_profile import classify_content_profile
from .execution_dag import execute_capability_dag


def validate_generation_execution(result: dict, *, required: bool = True) -> dict:
    result = dict(result or {})
    executed = [item for item in result.get("executed", []) if isinstance(item, dict) and item.get("output_hash")]
    if required and not executed:
        result["passed"] = False
        result["failures"] = list(result.get("failures") or []) + ["required_capability_not_executed"]
    else:
        result["passed"] = not bool(result.get("failures"))
    return result


def execute_generation_capabilities(draft: dict, brief: dict | None = None) -> dict:
    brief = brief or {}
    profile = brief.get("content_profile") or classify_content_profile(
        f"{draft.get('title', '')} {draft.get('body', '')}",
        platform=str(brief.get("platform") or ""),
        content_format=str(brief.get("content_form") or "article"),
    )
    runtime_context = _build_runtime_context(brief)
    registry = load_registry()
    matched = match_capabilities(profile, registry, runtime_context=runtime_context)
    # Do not execute render/assets/gate capabilities before their real stage.
    generation_stages = {"blueprint", "generation"}
    deferred = []
    candidates = []
    for item in matched.get("candidates", []):
        stage = str(item.get("stage") or "generation")
        if stage in generation_stages:
            candidates.append(item)
        else:
            deferred.append({**item, "status": "deferred", "reason": f"stage:{stage}"})
    matched["candidates"] = candidates
    matched["deferred"] = deferred
    def executor(item, current_draft, current_brief):
        capability = next(c for c in registry["capabilities"] if c["id"] == item["capability_id"])
        text = " ".join(
            str(value or "") for value in (current_draft.get("title"), current_draft.get("body", ""))
        ).strip()
        inputs = {
            "content_profile": profile,
            "content_blueprint": current_brief.get("content_blueprint") or {},
            "script_text": text,
            "segments": [str(current_draft.get("title") or ""), str(current_draft.get("body") or "")],
            "content_topic": str(current_draft.get("title") or ""),
            "target_audience": current_brief.get("target_audience") or "general",
            "platform": current_brief.get("platform") or profile.get("platform") or "",
        }
        if capability.get("kind") == "mcp_tool":
            inputs.update(
                {
                    "mcp_namespace": capability.get("mcp_namespace"),
                    "mcp_tool": capability.get("mcp_tool"),
                    "mcp_input": current_brief.get("mcp_input") or {"query": text},
                    "affected_output": current_brief.get("affected_output") or "generation_context",
                    **runtime_context,
                }
            )
        return execute_capability(capability, inputs)

    result = execute_capability_dag(matched, draft, brief, executor=executor)
    result = validate_generation_execution(result, required=bool(brief.get("automated_workflow")))
    result["profile"] = profile
    result["skipped"] = matched.get("skipped", [])
    result["inventory"] = matched.get("inventory", [])
    result["deferred"] = matched.get("deferred", [])
    return result


def _build_runtime_context(brief: dict) -> dict:
    context = brief.get("mcp_runtime")
    if context is None:
        context = brief.get("runtime_context")
    if context is None:
        context = brief.get("runtime")
    caller = brief.get("mcp_caller")
    if caller is None and isinstance(context, dict):
        caller = context.get("mcp_caller")
    if caller is None and context is not None:
        caller = getattr(context, "mcp_caller", None)
    return {"mcp_caller": caller, "mcp_runtime": context}
