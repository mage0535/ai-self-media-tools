#!/usr/bin/env bash
# A systemd-safe entrypoint. Keep scheduling policy out of a quoted unit line.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
bin="${CONTENT_PLATFORM_BIN:?CONTENT_PLATFORM_BIN is required}"
day="$(date +%F)"
out="$root/data/overnight/$day"
slots="$root/secrets/overnight-slots.json"
mkdir -p "$out"

notify() {
  "$root/scripts/notify_hermes_progress.sh" "overnight" "$1" "${2:-}" || true
}
trap 'status=$?; notify "failed" "batch_exit_${status}"' ERR

# Persistent timers may fire after a reboot. Do not turn a missed midnight run
# into morning contention; only the planned midnight admission window is valid.
hhmm="$(date +%H%M)"
if (( 10#$hhmm > 15 )); then
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

"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  performance-cycle --output-dir "$root/data/performance/daily" \
  --hermes-platform-scraper > "$out/performance-cycle-result.json"
notify "progress" "performance_cycle_complete"
"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-prepare --slots "$slots" --output "$out/prepared.json" --refresh > "$out/prepare-result.json"
notify "progress" "overnight_prepare_complete"
"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-plan --tasks "$out/prepared.json" --output "$out/plan.json" \
  --start-minute 0 --deadline-minute 290 --finalization-minutes 10 > "$out/plan-result.json"
notify "progress" "overnight_plan_complete"
"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-run --plan "$out/plan.json" --state "$out/state.json" --events "$out/events.jsonl" > "$out/result.json"
notify "completed" "batch_complete"
