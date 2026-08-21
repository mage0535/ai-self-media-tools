"""Fail-closed acceptance for overnight batch results and real artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = {"completed", "partial", "blocked", "failed", "no_run"}
VIDEO_PLATFORMS = {"bilibili", "douyin", "douyin_ai", "douyin_pet", "shipinhao", "xiaohongshu", "youtube", "tiktok", "kuaishou"}


def validate_overnight_result(result_path: str | Path, state_path: str | Path) -> dict[str, Any]:
    failures: list[str] = []
    result = _load_json(Path(result_path), failures, "result_empty")
    state = _load_json(Path(state_path), failures, "state_empty")
    status = str(result.get("status") or state.get("status") or "")
    if status not in ALLOWED_STATUSES:
        failures.append("status_not_allowed")
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    for task in tasks:
        platform = str(task.get("platform") or "")
        task_state = str(task.get("state") or "")
        if task_state not in {"staged", "handoff_ready", "published", "blocked", "failed", "deferred"}:
            continue
        artifacts = _artifact_paths(task)
        if task_state == "staged" and not any(path.is_file() for _, path in artifacts):
            failures.append(f"draft_artifacts_missing:{platform}")
        if task_state in {"staged", "handoff_ready"} and platform in VIDEO_PLATFORMS:
            kinds = {kind for kind, path in artifacts if path.is_file()}
            required = {"video", "cover", "publish_info"}
            if not required.issubset(kinds):
                failures.append(f"video_artifacts_missing:{platform}")
            output_dirs = {path.parent for _, path in artifacts if path.is_file()}
            for output_dir in output_dirs:
                if not (output_dir / "scene_manifest.json").is_file():
                    failures.append(f"scene_manifest_missing:{platform}")
                if not (output_dir / "tts_config.json").is_file():
                    failures.append(f"tts_config_missing:{platform}")
    return {"passed": not failures, "status": status, "failures": failures, "task_count": len(tasks)}


def _load_json(path: Path, failures: list[str], empty_failure: str) -> dict[str, Any]:
    try:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            failures.append(empty_failure)
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        failures.append(empty_failure)
        return {}


def _artifact_paths(task: dict[str, Any]) -> list[tuple[str, Path]]:
    rows = []
    for artifact in task.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("path"):
            rows.append((str(artifact.get("kind") or "unknown"), Path(str(artifact["path"]))))
    return rows
