#!/usr/bin/env bash
# Systemd entrypoint with bounded, non-secret Hermes progress notifications.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
data_root="${CONTENT_PLATFORM_DATA_DIR:?CONTENT_PLATFORM_DATA_DIR is required}"
secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:?CONTENT_PLATFORM_SECRETS_DIR is required}"
config_path="${CONTENT_PLATFORM_CONFIG:?CONTENT_PLATFORM_CONFIG is required}"
out="$data_root/performance/daily"
mkdir -p "$out"
notify() { "$root/scripts/notify_hermes_progress.sh" "growth-cycle" "$1" "${2:-}" || true; }
run_platform() { PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform "$@"; }

notify "started" "performance_cycle_started"
if run_platform --config "$config_path" --db "$data_root/state.db" \
  performance-cycle --platform wechat --platform kuaishou --platform bilibili --platform zhihu \
  --platform juejin --platform douyin --platform shipinhao --platform xiaohongshu \
  --platform youtube --platform tiktok --platform x \
  --collector-config "$secrets_root/performance-collector.json" \
  --output-dir "$out" --hermes-platform-scraper > "$out/systemd-last.json"; then
  notify "completed" "performance_cycle_complete"
else
  status=$?
  notify "failed" "performance_cycle_exit_${status}"
  exit "$status"
fi

if run_platform --config "$config_path" --db "$data_root/state.db" \
  metric-collect-due > "$out/metric-collect-due.json"; then
  notify "completed" "publication_metric_windows_processed"
else
  status=$?
  notify "failed" "publication_metric_windows_exit_${status}"
  exit "$status"
fi
