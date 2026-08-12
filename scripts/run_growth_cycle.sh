#!/usr/bin/env bash
# Systemd entrypoint with bounded, non-secret Hermes progress notifications.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
bin="${CONTENT_PLATFORM_BIN:-${HOME:?HOME is required}/.local/bin/content-platform}"
out="$root/data/performance/daily"
mkdir -p "$out"
notify() { "$root/scripts/notify_hermes_progress.sh" "growth-cycle" "$1" "${2:-}" || true; }

notify "started" "performance_cycle_started"
if "$bin" --config "$root/config.json" --db "$root/data/state.db" \
  performance-cycle --platform wechat --platform kuaishou --platform bilibili --platform zhihu \
  --platform juejin --platform douyin --platform shipinhao --platform xiaohongshu \
  --platform youtube --platform tiktok --platform x \
  --collector-config "$root/secrets/performance-collector.json" \
  --output-dir "$out" --hermes-platform-scraper > "$out/systemd-last.json"; then
  notify "completed" "performance_cycle_complete"
else
  status=$?
  notify "failed" "performance_cycle_exit_${status}"
  exit "$status"
fi
