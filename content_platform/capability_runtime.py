"""Execute generation-stage capabilities and produce fail-closed evidence."""

from __future__ import annotations

from .adapter_executor import execute_capability
from .capability_router import load_registry, match_capabilities
from .content_profile import classify_content_profile
from .execution_dag import execute_capability_dag
from .execution_trace import merge_execution_manifests, record_execution_stage


def validate_generation_execution(result: dict, *, required: bool = True) -> dict:
    result = dict(result or {})
    executed = [item for item in result.get("executed", []) if isinstance(item, dict) and item.get("output_hash")]
    executed_ids = {str(item.get("capability_id") or "") for item in executed}
    completed_stages = set(result.get("completed_stages") or [])
    selected_required = [
        str(item.get("capability_id") or "")
        for item in result.get("selected", [])
        if isinstance(item, dict)
        and str(item.get("required_or_optional") or "required") != "optional"
        and item.get("capability_id")
        and (not completed_stages or str(item.get("stage") or "generation") in completed_stages)
    ]
    missing_required = [capability_id for capability_id in selected_required if capability_id not in executed_ids]
    if required and not executed:
        result["passed"] = False
        result["failures"] = list(result.get("failures") or []) + ["required_capability_not_executed"]
    elif required and missing_required:
        result["passed"] = False
        result["failures"] = list(result.get("failures") or []) + [
            f"required_capability_not_executed:{capability_id}" for capability_id in missing_required
        ]
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
            "compiled_strategy": current_brief.get("compiled_strategy")
            or (current_brief.get("strategy") if isinstance(current_brief.get("strategy"), dict) and current_brief.get("strategy", {}).get("version") == "compiled_strategy_v1" else {})
            or ((current_brief.get("platform_strategy") or {}).get("compiled") if isinstance(current_brief.get("platform_strategy"), dict) else {})
            or ((current_brief.get("strategy") or {}).get("compiled") if isinstance(current_brief.get("strategy"), dict) else {}),
            "growth_strategy_evidence": current_brief.get("growth_strategy_evidence") or {},
            "platform_source_matrix": current_brief.get("platform_source_matrix") or {},
            "performance_evidence": current_brief.get("historical_feedback") or {},
            "topic_dedup_evidence": _dedup_evidence(current_brief.get("content_hygiene") or {}),
            "preflight_manifest": current_brief.get("preflight_manifest") or {},
            "query": text,
            "documents": current_brief.get("search_documents") or [],
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

    result = execute_capability_dag(
        matched,
        draft,
        brief,
        executor=executor,
        stages={"collection", "selection", "blueprint", "generation"},
    )
    result = validate_generation_execution(result, required=bool(brief.get("automated_workflow")))
    result["profile"] = profile
    result["skipped"] = matched.get("skipped", [])
    result["inventory"] = matched.get("inventory", [])
    result["deferred"] = list(result.get("pending") or [])
    return result


def _dedup_evidence(hygiene: dict) -> dict:
    if not isinstance(hygiene, dict) or not hygiene:
        return {}
    return {
        "lookback_days": 7,
        "passed": hygiene.get("status") not in {"blocked"},
        "duplicate_found": hygiene.get("status") == "blocked",
        "matches": list(hygiene.get("matches") or []),
        "topic_dedup_report": dict(hygiene),
    }


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
    if caller is None:
        caller = _project_mcp_caller(brief)
    return {"mcp_caller": caller, "mcp_runtime": context}


def _project_mcp_caller(brief: dict):
    """Invoke only handlers registered by the checked-in content MCP server."""
    def call(namespace, tool, payload, _runtime=None):
        if namespace != "content-platform":
            raise ValueError("unsupported content MCP namespace")
        from .mcp_server import invoke_registered_tool
        if tool == "content_search":
            documents = []
            for key in ("same_lane_intelligence", "hot_work_parameter_pack", "historical_feedback"):
                value = brief.get(key)
                if isinstance(value, dict):
                    documents.append({"id": key, "title": key, "text": str(value)[:4000]})
            return invoke_registered_tool("content_search", {"query": (payload or {}).get("query", ""), "documents": __import__("json").dumps(documents, ensure_ascii=False)})
        if tool == "memory_context":
            context = {
                "historical_feedback": brief.get("historical_feedback") or {},
                "compiled_skill_rule_ids": [
                    str(row.get("id") or "")
                    for row in ((brief.get("compiled_skill_rules") or {}).get("rules") or [])
                    if isinstance(row, dict) and row.get("id")
                ][:64],
            }
            return invoke_registered_tool("memory_context", {"context": __import__("json").dumps(context, ensure_ascii=False)})
        if tool == "build_content_recipe":
            packet = {"platform": brief.get("platform") or "", **(brief.get("content_blueprint") or {})}
            return invoke_registered_tool("build_content_recipe", {"packet": __import__("json").dumps(packet, ensure_ascii=False), "platform": packet["platform"]})
        raise ValueError("unsupported content MCP namespace/tool")
    return call
