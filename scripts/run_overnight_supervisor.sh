#!/usr/bin/env bash
# Independent heartbeat watcher for the overnight batch. It never republishes.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
day="$(date +%F)"
out="$root/data/overnight/$day"
state="$out/state.json"
heartbeat="$out/heartbeat.json"
report="$out/supervisor-report.json"

[[ -f "$state" ]] || exit 0

notify() {
  "$root/scripts/notify_hermes_progress.sh" "overnight-supervisor" "$1" "${2:-}" || true
}

run_platform() {
  PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform "$@"
}

# Always reconcile terminal snapshots too: state vocabulary changes must not
# wait for a future stale-heartbeat incident before becoming operator-visible.
run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-sync-state --state "$state" --output "$out/acceptance_summary.json" > "$out/supervisor-sync.json"

run_platform --config "$root/config.json" --db "$root/data/state.db" \
  overnight-supervise --state "$state" --heartbeat "$heartbeat" \
  --stale-after-seconds "${OVERNIGHT_HEARTBEAT_STALE_SECONDS:-1800}" > "$report"

status="$(python3 - "$report" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", "missing"))
PY
)"

if [[ "$status" != "stale" ]]; then
  exit 0
fi

# A stale service may own browser or publisher state. Recover only durable
# leases and reconcile facts; a new batch is never started from this watcher.
run_platform --config "$root/config.json" --db "$root/data/state.db" recover > "$out/supervisor-recover.json" || true
if [[ -f "$out/plan.json" ]]; then
  notify "progress" "automatic_recovery_started; see $report"
  if run_platform --config "$root/config.json" --db "$root/data/state.db" \
    overnight-run --plan "$out/plan.json" --state "$state" --events "$out/events.jsonl" \
    > "$out/supervisor-recovery-result.json"; then
    run_platform --config "$root/config.json" --db "$root/data/state.db" \
      overnight-sync-state --state "$state" --output "$out/acceptance_summary.json" \
      > "$out/supervisor-recovery-sync.json"
    notify "resolved" "automatic_recovery_completed; see $out/supervisor-recovery-result.json"
  else
    notify "action_required" "automatic_recovery_failed; see $out/supervisor-recovery-result.json"
  fi
else
  notify "action_required" "heartbeat_stale_reconciled_without_plan; see $report"
fi
