#!/usr/bin/env python3
"""Content-addressed checkpoints for resumable, serial video rendering."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def fingerprint_paths(paths: list[Path]) -> list[dict[str, Any]]:
    return [_file_signature(Path(path)) for path in paths if Path(path).is_file()]


def _state_path(video_dir: Path, stage: str) -> Path:
    return Path(video_dir) / ".render_state" / f"{stage}.json"


def mark_complete(video_dir: Path, stage: str, inputs: dict[str, Any], outputs: list[Path]) -> dict[str, Any]:
    video_dir = Path(video_dir)
    output_paths = [Path(path) for path in outputs]
    if not output_paths or not all(path.is_file() for path in output_paths):
        raise ValueError(f"cannot checkpoint {stage}: required outputs missing")
    state = {
        "stage": stage,
        "input_hash": _stable_hash(inputs),
        "inputs": inputs,
        "outputs": [_file_signature(path) for path in output_paths],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _state_path(video_dir, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def stage_current_or_adopt(
    video_dir: Path,
    stage: str,
    inputs: dict[str, Any],
    outputs: list[Path],
    *,
    legacy_marker: str = "",
) -> dict[str, Any]:
    """Return whether a stage is reusable; adopt valid legacy done markers once."""
    video_dir = Path(video_dir)
    output_paths = [Path(path) for path in outputs]
    if not output_paths or not all(path.is_file() for path in output_paths):
        return {"current": False, "reason": "outputs_missing", "stage": stage}
    expected_hash = _stable_hash(inputs)
    state_path = _state_path(video_dir, stage)
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"current": False, "reason": "checkpoint_invalid", "stage": stage}
        if state.get("input_hash") != expected_hash:
            return {"current": False, "reason": "inputs_changed", "stage": stage}
        current_outputs = [_file_signature(path) for path in output_paths]
        if current_outputs != state.get("outputs"):
            return {"current": False, "reason": "outputs_changed", "stage": stage}
        return {"current": True, "reason": "checkpoint_match", "stage": stage, "checkpoint": str(state_path)}

    marker = video_dir / (legacy_marker or f"{stage}.done")
    if marker.is_file():
        state = mark_complete(video_dir, stage, inputs, output_paths)
        return {"current": True, "reason": "legacy_done_adopted", "stage": stage, "checkpoint": str(_state_path(video_dir, stage)), "state": state}
    return {"current": False, "reason": "checkpoint_missing", "stage": stage}
