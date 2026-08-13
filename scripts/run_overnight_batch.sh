#!/usr/bin/env bash
# A systemd-safe entrypoint. Keep scheduling policy out of a quoted unit line.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
day="$(date +%F)"
out="$root/data/overnight/$day"
slots="$root/secrets/overnight-slots.json"
mkdir -p "$out"

notify() {
  "$root/scripts/notify_hermes_progress.sh" "overnight" "$1" "${2:-}" || true
}
trap 'status=$?; notify "failed" "batch_exit_${status}"' ERR

# Persistent timers may fire after a reboot. Allow a bounded catch-up window,
# but never start an overnight batch late in the working day.
hhmm="$(date +%H%M)"
admission_window_minutes="${OVERNIGHT_ADMISSION_WINDOW_MINUTES:-60}"
if (( 10#$hhmm > admission_window_minutes )); then
  printf '%s\n' '{"status":"no_run","reason":"missed midnight start window"}' > "$out/result.json"
  notify "skipped" "missed_midnight_admission_window"
  exit 0
fi

if [[ ! -f "$slots" ]]; then
  printf '%s\n' '{"status":"no_slots"}' > "$out/result.json"
  notify "skipped" "no_due_slots"
  exit 0
fi

notify "started" "batch_started"

run_platform() {
  PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform "$@"
}

if ! "$root/scripts/smoke_provider.sh" "$root/config.json"; then
  printf '%s\n' '{"status":"blocked","reason":"provider_preflight_failed"}' > "$out/result.json"
  notify "failed" "provider_preflight_failed"
  exit 1
fi
notify "progress" "provider_smoke_complete"

# Run the checked-out module, not a stale globally installed console script.
# The timer must execute exactly the Git revision that was audited and deployed.
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  performance-cycle --output-dir "$root/data/performance/daily" \
  --hermes-platform-scraper > "$out/performance-cycle-result.json"
notify "progress" "performance_cycle_complete"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-prepare --slots "$slots" --output "$out/prepared.json" --refresh > "$out/prepare-result.json"
notify "progress" "overnight_prepare_complete"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-plan --tasks "$out/prepared.json" --output "$out/plan.json" \
  --start-minute 0 --deadline-minute 290 --finalization-minutes 10 > "$out/plan-result.json"
notify "progress" "overnight_plan_complete"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-run --plan "$out/plan.json" --state "$out/state.json" --events "$out/events.jsonl" > "$out/result.json"
if ! run_platform overnight-acceptance --result "$out/result.json" --state "$out/state.json" --output "$out/acceptance_report.json" > "$out/acceptance-result.json"; then
  notify "failed" "overnight_acceptance_failed"
  exit 1
fi
notify "progress" "overnight_acceptance_complete"
batch_status="$(python3 - "$out/result.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload.get("status", "failed"))
PY
)"
case "$batch_status" in
  completed)
    notify "completed" "batch_complete"
    ;;
  partial)
    notify "partial" "batch_has_expected_blocked_tasks"
    ;;
  capacity_blocked|blocked)
    notify "failed" "batch_not_admitted_${batch_status}"
    exit 1
    ;;
  *)
    failed_count="$(python3 - "$out/result.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(sum(1 for task in payload.get("tasks", []) if task.get("state") == "failed"))
PY
)"
    notify "failed" "${failed_count}_tasks_failed_${batch_status}"
    exit 1
    ;;
esac
