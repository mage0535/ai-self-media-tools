"""Fail-closed adapter boundary for Hermes MCP tools."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable


def invoke_mcp_tool(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    allowlist: dict[str, set[str]],
    client: Callable[[str, str, dict[str, Any], int], Any],
    timeout: int = 30,
) -> dict[str, Any]:
    if tool not in (allowlist or {}).get(server, set()):
        return {"status": "failed", "reason": "mcp_tool_not_allowlisted"}
    if timeout <= 0:
        return {"status": "failed", "reason": "mcp_timeout_invalid"}
    started = time.monotonic()
    try:
        output = client(server, tool, arguments, timeout)
        raw = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str).encode()
        return {
            "status": "executed",
            "output_contract": "mcp_result_v1",
            "output_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {"status": "failed", "reason": f"mcp_error:{type(exc).__name__}", "duration_ms": round((time.monotonic() - started) * 1000)}
