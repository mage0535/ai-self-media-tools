#!/usr/bin/env bash
# Login expiry is an actionable data-source state, not a failed systemd worker.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
report="$root/data/performance/wechat_mp_daily_report.json"
notify() { "$root/scripts/notify_hermes_progress.sh" "wechat-metrics" "$1" "${2:-}" || true; }

notify "started" "metrics_refresh_started"
set +e
python3 "$root/scripts/wechat_mp_daily_metrics.py" \
  --db "$root/data/state.db" \
  --state-file "$root/secrets/wechat_mp_uploaded_state.json" \
  --metrics-file "$root/data/performance/wechat_mp_metrics.json" \
  --report "$report"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  notify "completed" "metrics_refresh_complete"
  exit 0
fi
if [[ -f "$report" ]] && grep -q '"status": "login_required"' "$report"; then
  notify "blocked" "creator_login_required"
  exit 0
fi
notify "failed" "metrics_refresh_exit_${status}"
exit "$status"
