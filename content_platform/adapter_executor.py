"""Execute only verified, allowlisted Python capability adapters."""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from typing import Any


_SUPPORTED_ADAPTERS = frozenset(
    {
        "python:content_platform.adapters.structure:execute",
        "python:content_platform.adapters.methodology:execute",
        "python:content_platform.adapters.search:execute",
        "python:content_platform.adapters.mcp:execute",
        "python:content_platform.adapters.runtime:execute",
    }
)


def supported_adapter_targets() -> frozenset[str]:
    return _SUPPORTED_ADAPTERS


def _failure(reason: str) -> dict[str, Any]:
    return {"status": "failed", "reason": reason, "contract_valid": False}


def capability_available(capability: dict[str, Any], inputs: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Probe the adapter module without calling the capability adapter."""
    if capability.get("lifecycle") != "executable":
        return False, "inventory_only"
    adapter = str(capability.get("adapter") or "")
    if adapter not in _SUPPORTED_ADAPTERS:
        return False, "adapter_not_allowlisted"
    probe = str(capability.get("availability_probe") or "")
    if not probe.startswith("module:"):
        return False, "availability_probe_not_allowlisted"
    module_name = probe.removeprefix("module:")
    if not module_name.startswith("content_platform.adapters."):
        return False, "availability_probe_not_allowlisted"
    try:
        module = importlib.import_module(module_name)
        if not callable(getattr(module, "execute", None)):
            return False, "availability_probe_missing_callable"
        probe_callable = getattr(module, "probe", None)
        if callable(probe_callable):
            probe_result = probe_callable(capability, inputs or {})
            if isinstance(probe_result, tuple) and len(probe_result) == 2 and probe_result[0] is not True:
                return bool(probe_result[0]), str(probe_result[1])
    except Exception as exc:
        return False, f"availability_probe_error:{type(exc).__name__}"
    return True, "available"


def execute_capability(capability: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    for required in capability.get("required_inputs", []):
        if required not in inputs or inputs[required] in (None, "", []):
            return _failure(f"missing_input:{required}")
    available, reason = capability_available(capability, inputs)
    if not available:
        if capability.get("kind") == "mcp_tool":
            evidence = _execute_mcp_evidence(capability, inputs)
            if evidence is not None:
                return evidence
        return {"status": "skipped", "reason": reason, "contract_valid": False}
    adapter = str(capability["adapter"])
    target = adapter.removeprefix("python:")
    module_name, separator, function_name = target.rpartition(":")
    if not separator or not module_name.startswith("content_platform.adapters."):
        return _failure("adapter_target_not_allowlisted")
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        adapter_inputs = dict(inputs)
        adapter_inputs["_capability"] = capability
        output = function(adapter_inputs)
    except Exception as exc:
        return _failure(f"adapter_error:{type(exc).__name__}:{exc}")
    if not isinstance(output, dict) or not output:
        return _failure("adapter_output_empty")
    contract_valid = _validate_contract(output, str(capability.get("output_contract") or ""))
    duration_ms = int((time.perf_counter() - started) * 1000)
    if not contract_valid:
        return {
            "status": "failed",
            "reason": "output_contract_invalid",
            "output": output,
            "contract_valid": False,
            "duration_ms": duration_ms,
        }
    serialized = json.dumps(_stable_hash_value(output), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    adapter_status = str(output.get("status") or "")
    non_success = {"skipped", "failed", "fallback", "degraded"}
    evidence_states = {"planned", "consulted", "executed"}
    status = (
        adapter_status
        if adapter_status in non_success | evidence_states
        else "consulted" if capability.get("kind") == "methodology" else "executed"
    )
    result = {
        "status": status,
        "output": output,
        "duration_ms": duration_ms,
        "output_hash": "sha256:" + hashlib.sha256(serialized).hexdigest(),
        "contract_valid": status not in {"skipped", "failed", "fallback", "degraded"},
    }
    if status in non_success:
        result["reason"] = output.get("reason") or "adapter_reported_failure"
    return result


def _execute_mcp_evidence(capability: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any] | None:
    adapter = str(capability.get("adapter") or "")
    target = adapter.removeprefix("python:")
    module_name, separator, function_name = target.rpartition(":")
    if not separator or module_name != "content_platform.adapters.mcp" or function_name != "execute":
        return None
    try:
        module = importlib.import_module(module_name)
        output = getattr(module, function_name)({**inputs, "_capability": capability})
    except Exception:
        return None
    if not isinstance(output, dict) or not _validate_contract(output, "mcp_evidence_v1"):
        return None
    serialized = json.dumps(_stable_hash_value(output), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    status = str(output.get("status") or "skipped")
    return {
        "status": status,
        "output": output,
        "duration_ms": 0,
        "output_hash": "sha256:" + hashlib.sha256(serialized).hexdigest(),
        "contract_valid": False,
        "reason": output.get("reason") or "mcp_unavailable",
    }


def _stable_hash_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable_hash_value(item) for key, item in value.items() if key != "duration_ms"}
    if isinstance(value, list):
        return [_stable_hash_value(item) for item in value]
    return value


def _validate_contract(output: dict[str, Any], contract: str) -> bool:
    runtime_contracts = {
        "compiled_strategy_v1",
        "platform_source_matrix_v2",
        "performance_evidence_v1",
        "topic_dedup_evidence_v1",
        "content_recipe_v1",
        "seo_geo_v1",
        "visual_recipe_v1",
        "video_template_plan_v1",
        "shotcraft_plan_v1",
        "tts_plan_v1",
        "subtitle_plan_v1",
        "audio_mix_plan_v1",
        "media_quality_v1",
        "preflight_manifest_v1",
    }
    if contract in runtime_contracts:
        return (
            output.get("version") == contract
            and output.get("status") == "failed"
            and isinstance(output.get("runtime_evidence"), dict)
        ) or (
            output.get("version") == contract
            and output.get("status") in {"verified", "planned", "consulted", "executed"}
            and isinstance(output.get("runtime_evidence"), dict)
            and isinstance(output.get("evidence"), dict)
        )
    if contract == "structure_match_v1":
        return output.get("version") == contract and isinstance(output.get("matched_structures"), list)
    if contract == "reference_compilation_v1":
        rule_ids = output.get("rule_ids")
        rules_applied = output.get("rules_applied")
        rule_sources = output.get("rule_sources")
        source_hashes = output.get("source_hashes")
        return output.get("version") == contract and all(
            isinstance(output.get(field), expected)
            for field, expected in {
                "rule_ids": list,
                "source_hashes": dict,
                "rule_sources": dict,
                "rules_applied": list,
                "affected_outputs": list,
            }.items()
        ) and all(
            rule_id in rule_ids
            and str(rule_sources.get(rule_id) or "").strip()
            and str(source_hashes.get(rule_sources[rule_id]) or "").strip()
            for rule_id in rules_applied
        ) and not output.get("status") in {"failed", "fallback", "degraded", "skipped"}
    if contract == "search_result_v1":
        return output.get("version") == contract and isinstance(output.get("result_ids"), list) and isinstance(output.get("results"), list)
    if contract == "mcp_evidence_v1":
        return output.get("version") == contract and all(
            isinstance(output.get(field), str)
            for field in ("server_name", "tool_name", "input_hash", "output_hash", "affected_output")
        ) and output.get("status") in {"executed", "skipped", "failed", "fallback", "degraded"}
    return False
