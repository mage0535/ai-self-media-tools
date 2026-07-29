"""Suggestion-only strategy updater; never mutates channel strategy automatically."""

from __future__ import annotations

import uuid
from typing import Any


def build_strategy_suggestion(account_id: str, content_package_ids: list[str], recommendation: dict[str, Any], confidence: str = "low") -> dict[str, Any]:
    return {
        "suggestion_id": f"sug_{uuid.uuid4().hex[:12]}",
        "account_id": account_id,
        "based_on_content_packages": list(content_package_ids),
        "recommendation": dict(recommendation),
        "confidence": confidence,
        "auto_apply": False,
    }
