#!/usr/bin/env bash
# Read-only, stable-output source for Hermes monitor-mode reporting.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:-${HOME:?HOME is required}/.ai-self-media-tools}"
day="$(date +%F)"
directory="$root/data/overnight/$day"
state="$directory/state.json"
events="$directory/events.jsonl"

[[ -d "$directory" ]] || exit 0

python3 - "$state" "$events" "$directory" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path, events_path, directory = map(Path, sys.argv[1:])
state = {}
if state_path.is_file():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {"status": "state_unreadable"}
latest = {}
last_event_at = None
if events_path.is_file():
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        platform = str(row.get("platform") or "")
        raw_at = row.get("at")
        if raw_at:
            try:
                observed = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                if last_event_at is None or observed > last_event_at:
                    last_event_at = observed
            except ValueError:
                pass
        if platform:
            latest[platform] = {key: value for key, value in row.items() if key != "at"}
tasks = []
for task in state.get("tasks", []) if isinstance(state, dict) else []:
    tasks.append({key: task.get(key) for key in ("platform", "state", "pipeline_state", "job_id", "reason") if task.get(key) not in (None, "")})
batch_status = state.get("status", "waiting_for_checkpoint")
last_progress_at = last_event_at
if last_progress_at is None:
    last_progress_at = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
stalled = batch_status in {"running", "waiting_for_checkpoint"} and (datetime.now(timezone.utc) - last_progress_at).total_seconds() > 9 * 60
print(json.dumps({"batch_status": batch_status, "stalled": stalled, "stall_reason": "no progress event or checkpoint for over nine minutes" if stalled else "", "tasks": tasks, "latest_events": latest}, ensure_ascii=False, sort_keys=True))
PY
