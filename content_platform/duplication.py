"""Deterministic first-pass content duplication checks."""

from __future__ import annotations

from typing import Any

from .models import GateFailure, GateResult


def check_exact_duplicates(content_package: dict[str, Any], store: Any, lookback_limit: int = 200) -> GateResult:
    failures: list[GateFailure] = []
    title = str(content_package.get("title", "")).strip().casefold()
    topic = str(content_package.get("topic", "")).strip().casefold()
    account_id = str(content_package.get("account_id", "")).strip()
    platform = str(content_package.get("platform", "")).strip()
    current_id = str(content_package.get("content_package_id", ""))
    for row in store.content_packages(platform=platform, limit=lookback_limit):
        payload = row.get("payload", {})
        if payload.get("content_package_id") == current_id:
            continue
        if account_id and str(payload.get("account_id", "")) != account_id:
            continue
        if title and title == str(payload.get("title", "")).strip().casefold():
            failures.append(
                GateFailure("TITLE_EXACT_DUPLICATE", "D1.1", "warning", "Same-account exact title duplicate was found.", "Rewrite the title or record an override reason.")
            )
        if topic and topic == str(payload.get("topic", "")).strip().casefold():
            failures.append(
                GateFailure("TOPIC_EXACT_DUPLICATE", "D1.6", "warning", "Same-account exact topic duplicate was found.", "Change the angle or record follow_up_to, difference_angle, and recap_reason.")
            )
    mode = "shadow" if any(f.severity == "info" for f in failures) else "enforce"
    return GateResult("duplication_detector", "failed" if failures else "passed", failures, mode=mode)
