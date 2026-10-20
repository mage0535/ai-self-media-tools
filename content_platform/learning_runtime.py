"""Fail-closed legacy runtime projection.

JSON ``LearningRegistry`` records are retained only for migration/audit.  They
are not an authorization source and can never enable owned-learning automation.
SQLite ``OwnedLearningStore.strategy_health`` is the sole future authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_learning_runtime(registry_path: str | Path) -> dict[str, Any]:
    path = Path(registry_path)
    return {
        "version": "learning_runtime_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "legacy_registry_disabled" if path.is_file() else "not_configured",
        "allow_automated_learning": False,
        "policies": [],
        "reason": "json_registry_is_not_a_production_authorization_source",
    }
