"""Deterministic, lightweight delivery controls for Edge TTS segments."""

from __future__ import annotations

from typing import Any


_PROFILES = (
    {"style": "urgent", "rate": "+8%", "pitch": "+3Hz", "pause_after_ms": 300},
    {"style": "calm", "rate": "-3%", "pitch": "+0Hz", "pause_after_ms": 420},
    {"style": "grounded", "rate": "+0%", "pitch": "-1Hz", "pause_after_ms": 360},
    {"style": "warm", "rate": "+3%", "pitch": "+2Hz", "pause_after_ms": 480},
)


def build_voice_plan(segments: list[str]) -> list[dict[str, Any]]:
    """Assign bounded prosody controls without adding a resident TTS model."""
    plan: list[dict[str, Any]] = []
    for index, text in enumerate(segments):
        profile = _PROFILES[min(index, len(_PROFILES) - 1)]
        plan.append({"index": index, "text": str(text), **profile})
    return plan


def validate_voice_plan(plan: list[dict[str, Any]] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(plan, list) or not plan:
        failures.append("voice_plan_missing")
    else:
        required = {"index", "text", "style", "rate", "pitch", "pause_after_ms"}
        if any(not isinstance(row, dict) or not required.issubset(row) for row in plan):
            failures.append("voice_plan_segment_invalid")
    return {"passed": not failures, "failures": failures}
