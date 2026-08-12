#!/usr/bin/env bash
# Read-only, stable-output source for Hermes monitor-mode reporting.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:-${HOME:?HOME is required}/.ai-self-media-tools}"
day="$(date +%F)"
directory="$root/data/overnight/$day"
state="$directory/state.json"
events="$directory/events.jsonl"

[[ -f "$state" || -f "$events" ]] || exit 0

python3 - "$state" "$events" <<'PY'
import json
import sys
from pathlib import Path

state_path, events_path = map(Path, sys.argv[1:])
state = {}
if state_path.is_file():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {"status": "state_unreadable"}
latest = {}
if events_path.is_file():
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        platform = str(row.get("platform") or "")
        if platform:
            latest[platform] = {key: value for key, value in row.items() if key != "at"}
tasks = []
for task in state.get("tasks", []) if isinstance(state, dict) else []:
    tasks.append({key: task.get(key) for key in ("platform", "state", "pipeline_state", "job_id", "reason") if task.get(key) not in (None, "")})
print(json.dumps({"batch_status": state.get("status", "waiting"), "tasks": tasks, "latest_events": latest}, ensure_ascii=False, sort_keys=True))
PY
