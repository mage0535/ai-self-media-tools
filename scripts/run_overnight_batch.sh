#!/usr/bin/env bash
# A systemd-safe entrypoint. Keep scheduling policy out of a quoted unit line.
set -euo pipefail

# 2026-08-15: 持久化发布代理（cron 环境无 .env），国际/国内平台发布必需。
# 不覆盖外部已注入的值。
export US_PROXY="${US_PROXY:-http://127.0.0.1:2080}"
export CN_PROXY="${CN_PROXY:-socks5://127.0.0.1:1080}"

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
day="$(date +%F)"
out="$root/data/overnight/$day"
slots="$root/secrets/overnight-slots.json"
mkdir -p "$out"

notify() {
  "$root/scripts/notify_hermes_progress.sh" "overnight" "$1" "${2:-}" || true
}
trap 'status=$?; notify "failed" "batch_exit_${status}"' ERR

# Persistent timers may fire after a reboot. Permit one bounded catch-up hour,
# then leave the morning window to interactive work and reporting.
admission_window_minutes="${OVERNIGHT_ADMISSION_WINDOW_MINUTES:-60}"
hhmm="$(date +%H%M)"
minutes_since_midnight=$((10#$hhmm / 100 * 60 + 10#$hhmm % 100))
if (( minutes_since_midnight > admission_window_minutes )); then
  printf '%s\n' '{"status":"no_run","reason":"missed overnight admission window"}' > "$out/result.json"
  notify "skipped" "missed_overnight_admission_window"
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
  health-refresh --output "$root/data/delivery_health_state.json" > "$out/delivery-health-result.json"
notify "progress" "delivery_health_refreshed"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-prepare --slots "$slots" --output "$out/prepared.json" --refresh > "$out/prepare-result.json"
notify "progress" "overnight_prepare_complete"
shadow_failures="$(python3 - "$out/prepared.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(sum(
    1
    for task in payload.get("tasks", [])
    if (task.get("trend_evidence_gate") or {}).get("mode") == "shadow"
    and not (task.get("trend_evidence_gate") or {}).get("passed")
))
PY
)"
if (( shadow_failures > 0 )); then
  notify "action_required" "trend_evidence_shadow_failures_${shadow_failures}; enforcement_not_enabled"
fi
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-plan --tasks "$out/prepared.json" --output "$out/plan.json" \
  --start-minute 0 --deadline-minute 290 --finalization-minutes 10 > "$out/plan-result.json"
notify "progress" "overnight_plan_complete"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-run --plan "$out/plan.json" --state "$out/state.json" --events "$out/events.jsonl" > "$out/result.json"
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-sync-state --state "$out/state.json" --output "$out/acceptance_summary.json" > "$out/sync-state-result.json"
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
    notify "partial" "batch_partial_requires_follow_up"
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
