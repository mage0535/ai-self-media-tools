#!/usr/bin/env python3
"""Small, append-only timing evidence for serial video renders."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _timing_path(video_dir: Path) -> Path:
    return Path(video_dir) / "render_timing.json"


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = payload.get("events", []) if isinstance(payload, dict) else []
        return [event for event in events if isinstance(event, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def record_stage_timing(video_dir: Path, stage: str, seconds: float, *, cached: bool) -> Path:
    """Persist one stage result without making a render failure fatal."""
    path = _timing_path(Path(video_dir))
    events = _load_events(path)
    events.append(
        {
            "stage": str(stage),
            "seconds": round(max(0.0, float(seconds)), 3),
            "cached": bool(cached),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"events": events[-100:]}, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return path


def load_timing_summary(video_dir: Path) -> dict[str, Any]:
    events = _load_events(_timing_path(Path(video_dir)))
    slowest = sorted(events, key=lambda event: float(event.get("seconds", 0.0)), reverse=True)
    return {
        "stage_count": len(events),
        "total_seconds": round(sum(float(event.get("seconds", 0.0)) for event in events), 3),
        "slowest": slowest[:10],
    }


def write_timing_summary(video_dir: Path) -> Path:
    """Write a compact, human-readable summary beside the raw timing events."""
    summary = load_timing_summary(video_dir)
    path = Path(video_dir) / "render_timing_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
