"""Secure allowlisted adapter executor."""

from __future__ import annotations

import hashlib
import importlib
import json
import time


def execute_capability(capability: dict, inputs: dict) -> dict:
    started = time.perf_counter()
    for required in capability.get("required_inputs", []):
        if required not in inputs or inputs[required] in (None, "", []):
            return {"status": "failed", "reason": f"missing_input:{required}", "contract_valid": False}
    kind = capability.get("capability_kind")
    if kind == "methodology":
        return {"status": "consulted", "contract_valid": True, "duration_ms": 0}
    adapter = str(capability.get("adapter") or "")
    if not adapter.startswith("python:"):
        return {"status": "failed", "reason": "adapter_not_allowlisted", "contract_valid": False}
    target = adapter.removeprefix("python:")
    module_name, separator, function_name = target.rpartition(":")
    if not separator or not module_name.startswith("content_platform.adapters."):
        return {"status": "failed", "reason": "adapter_target_not_allowlisted", "contract_valid": False}
    try:
        module = importlib.import_module(module_name)
        fn = getattr(module, function_name)
        output = fn(inputs)
        if not isinstance(output, dict) or not output:
            raise ValueError("adapter output must be a non-empty object")
        valid = _validate_contract(output, str(capability.get("output_contract") or ""))
        serialized = json.dumps(output, ensure_ascii=False, sort_keys=True).encode()
        return {
            "status": "executed" if valid else "failed",
            "output": output,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "output_hash": "sha256:" + hashlib.sha256(serialized).hexdigest(),
            "contract_valid": valid,
            **({} if valid else {"reason": "output_contract_invalid"}),
        }
    except Exception as exc:
        return {"status": "failed", "reason": f"adapter_error:{type(exc).__name__}:{exc}", "contract_valid": False}


def _validate_contract(output: dict, contract: str) -> bool:
    if contract == "structure_match_v1":
        return output.get("version") == contract and isinstance(output.get("matched_structures"), list)
    return bool(output)
