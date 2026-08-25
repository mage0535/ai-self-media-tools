"""Bounded MCP invocation adapter for content-production capabilities."""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any


_FORBIDDEN = frozenset({"trading", "trade", "stock", "stocks", "financial", "finance", "forex", "crypto"})


def _blocked(value: str) -> bool:
    tokens = {token for token in value.casefold().replace("_", "-").split("-") if token}
    return bool(tokens.intersection(_FORBIDDEN)) or any(token in value.casefold() for token in _FORBIDDEN)


def _allowed(capability: dict[str, Any], namespace: str, tool: str) -> bool:
    configured_namespace = str(capability.get("mcp_namespace") or "")
    configured_tool = str(capability.get("mcp_tool") or "")
    return bool(
        configured_namespace
        and configured_tool
        and namespace == configured_namespace
        and tool == configured_tool
        and not _blocked(configured_namespace)
    )


def _caller(inputs: dict[str, Any]) -> Any:
    return inputs.get("mcp_caller") or inputs.get("mcp_call")


def _runtime(inputs: dict[str, Any]) -> Any:
    return inputs.get("mcp_runtime") or inputs.get("runtime_context") or inputs.get("runtime")


def probe(capability: dict[str, Any], inputs: dict[str, Any]) -> tuple[bool, str]:
    namespace = str(capability.get("mcp_namespace") or "")
    tool = str(capability.get("mcp_tool") or "")
    if not _allowed(capability, namespace, tool):
        return False, "mcp_tool_not_allowlisted"
    if inputs.get("mcp_namespace", namespace) != namespace or inputs.get("mcp_tool", tool) != tool:
        return False, "mcp_not_configured_for_capability"
    if callable(_caller(inputs)):
        return True, "configured"
    return False, "mcp_unavailable:invoker_not_configured"


def _safe_value(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    if any(token in lowered for token in ("secret", "cookie", "token", "password", "authorization", "raw")):
        return "[redacted]"
    if callable(value):
        return "[callable]"
    if isinstance(value, dict):
        return {str(k): _safe_value(v, str(k)) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, key) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def _hash(value: Any) -> str:
    payload = json.dumps(_safe_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _invoke(caller: Any, namespace: str, tool: str, payload: Any, runtime: Any) -> Any:
    target = caller if callable(caller) else getattr(caller, "call", None)
    if not callable(target):
        raise TypeError("mcp_caller_not_callable")
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return target(namespace, tool, payload, runtime)
    if _can_bind(signature, namespace, tool, payload, runtime):
        return target(namespace, tool, payload, runtime)
    return target(namespace, tool, payload)


def _can_bind(signature: inspect.Signature, *args: Any) -> bool:
    try:
        signature.bind(*args)
    except TypeError:
        return False
    return True


def _evidence(namespace: str, tool: str, input_hash: str, status: str, affected: str, started: float, *, output_hash: str = "", reason: str = "", fallback_used: bool = False) -> dict[str, Any]:
    result = {
        "version": "mcp_evidence_v1",
        "server_name": namespace,
        "tool_name": tool,
        "input_hash": input_hash,
        "output_hash": output_hash or "sha256:" + hashlib.sha256(b"").hexdigest(),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "status": status,
        "affected_output": affected,
        "affected_outputs": [affected],
        "fallback_used": fallback_used,
    }
    if reason:
        result["reason"] = reason
    return result


def execute(inputs: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    namespace = str(inputs.get("mcp_namespace") or "")
    tool = str(inputs.get("mcp_tool") or "")
    capability = inputs.get("_capability") or {}
    payload = inputs.get("mcp_input") or {}
    input_hash = _hash(payload)
    affected = str(inputs.get("affected_output") or "content_context")
    if not _allowed(capability, namespace, tool):
        return _evidence(namespace, tool, input_hash, "skipped", affected, started, reason="mcp_tool_not_allowlisted")
    expected_namespace = str(capability.get("mcp_namespace") or "")
    expected_tool = str(capability.get("mcp_tool") or "")
    if namespace != expected_namespace or tool != expected_tool:
        return _evidence(namespace, tool, input_hash, "skipped", affected, started, reason="mcp_not_configured_for_capability")
    call = _caller(inputs)
    fallback = inputs.get("mcp_fallback")
    if not callable(call):
        return _evidence(namespace, tool, input_hash, "skipped", affected, started, reason="mcp_unavailable:invoker_not_configured")
    timeout = max(0.001, float(inputs.get("mcp_timeout_seconds") or 10.0))
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_invoke, call, namespace, tool, payload, _runtime(inputs))
        raw_output = future.result(timeout=timeout)
        return _evidence(namespace, tool, input_hash, "executed", affected, started, output_hash=_hash(raw_output))
    except FutureTimeout:
        reason = "mcp_timeout"
    except Exception as exc:
        reason = f"mcp_call_failed:{type(exc).__name__}"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if callable(fallback):
        try:
            raw_output = fallback(namespace, tool, payload)
            return _evidence(namespace, tool, input_hash, "fallback", affected, started, output_hash=_hash(raw_output), reason=reason, fallback_used=True)
        except Exception as exc:
            reason = f"{reason};fallback_failed:{type(exc).__name__}"
    return _evidence(namespace, tool, input_hash, "failed", affected, started, reason=reason)
