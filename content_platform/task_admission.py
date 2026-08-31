"""Deterministic admission checks for production automated jobs."""

from __future__ import annotations

import os
from typing import Any

from .run_contract import validate_run_contract


class TaskAdmissionError(ValueError):
    pass


def validate_task_admission(platforms: list[str], brief: dict[str, Any]) -> dict[str, Any]:
    """Reject unsafe automated jobs before mutable state is created."""
    automated = brief.get("automated_workflow") is True
    production = os.environ.get("CONTENT_PLATFORM_RUNTIME_MODE", "").casefold() == "production"
    if not automated or not production:
        return {"passed": True, "mode": "manual_or_nonproduction"}
    if len(platforms) != 1:
        raise TaskAdmissionError("automated production jobs require exactly one platform")
    contract = brief.get("run_contract")
    if not isinstance(contract, dict):
        raise TaskAdmissionError("run_contract.missing")
    platform = str(platforms[0]).casefold()
    if str(contract.get("platform") or "").casefold() != platform:
        raise TaskAdmissionError("run_contract.platform_mismatch")
    validation = validate_run_contract(contract)
    if not validation["passed"]:
        raise TaskAdmissionError("invalid run contract: " + ",".join(validation["failures"]))
    return {"passed": True, "mode": "production_automated", "platform": platform}
