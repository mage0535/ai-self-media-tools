#!/usr/bin/env bash
# Login expiry is an actionable data-source state, not a failed systemd worker.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
data_root="${CONTENT_PLATFORM_DATA_DIR:?CONTENT_PLATFORM_DATA_DIR is required}"
secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:?CONTENT_PLATFORM_SECRETS_DIR is required}"
report="$data_root/performance/wechat_mp_daily_report.json"
notify() { "$root/scripts/notify_hermes_progress.sh" "wechat-metrics" "$1" "${2:-}" || true; }

notify "started" "metrics_refresh_started"
set +e
PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 "$root/scripts/wechat_mp_daily_metrics.py" \
  --db "$data_root/state.db" \
  --state-file "$secrets_root/wechat_mp_uploaded_state.json" \
  --metrics-file "$data_root/performance/wechat_mp_metrics.json" \
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
