#!/usr/bin/env bash
# A systemd-safe entrypoint. Keep scheduling policy out of a quoted unit line.
set -euo pipefail

# 2026-08-15: 持久化发布代理（cron 环境无 .env），国际/国内平台发布必需。
# 不覆盖外部已注入的值。
export US_PROXY="${US_PROXY:-http://127.0.0.1:2080}"
export CN_PROXY="${CN_PROXY:-socks5://127.0.0.1:1080}"

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
data_root="${CONTENT_PLATFORM_DATA_DIR:-$root/data}"
secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:-$root/secrets}"
config_path="${CONTENT_PLATFORM_CONFIG:-$root/config.json}"
day="$(date +%F)"
out="$data_root/overnight/$day"
slots="$secrets_root/overnight-slots.json"
mkdir -p "$out"

notify() {
  "$root/scripts/notify_hermes_progress.sh" "overnight" "$1" "${2:-}" || true
}

handle_error() {
  local status="$1"
  trap - ERR
  set +e
  if [[ ! -f "$out/result.json" ]]; then
    printf '{"status":"failed","reason":"batch_failed_before_result","exit_code":%s}\n' "$status" > "$out/result.json"
  fi
  if [[ -f "$out/state.json" ]]; then
    run_platform --config "$config_path" --db "$data_root/state.db" \
      overnight-sync-state --state "$out/state.json" --output "$out/acceptance_summary.json" > "$out/error-sync-state-result.json"
  fi
  notify "failed" "batch_failed_before_result_exit_${status}"
  exit "$status"
}
trap 'handle_error $?' ERR

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
run_platform --config "$config_path" --db "$data_root/state.db" \
  performance-cycle --output-dir "$data_root/performance/daily" \
  --hermes-platform-scraper > "$out/performance-cycle-result.json"
notify "progress" "performance_cycle_complete"
run_platform --config "$config_path" --db "$data_root/state.db" \
  health-refresh --output "$data_root/delivery_health_state.json" > "$out/delivery-health-result.json"
notify "progress" "delivery_health_refreshed"
hot_work_args=(
  hot-works-collect
  --platform wechat
  --platform kuaishou
  --platform douyin_ai
  --platform douyin_pet
  --query "wechat=AI工具 自动化 工作流 效率"
  --query "wechat=Claude Code Codex AI效率"
  --query "kuaishou=AI工具"
  --query "kuaishou=Claude Code Codex"
  --query "douyin_ai=AI工具"
  --query "douyin_pet=猫咪治愈"
  --output-dir "$out/hot-works"
)
for sample in "$data_root"/intel/hot_works_multiplatform_*/hot_works_raw_enriched_v2.json "$data_root"/intel/hot_works_multiplatform_*/*logged_samples.json; do
  if [[ -f "$sample" ]]; then
    hot_work_args+=(--sample-file "$sample")
  fi
done
if [[ -f "$data_root/intel/hot_works_multiplatform_20260822/cookie_probe/kuaishou_playwright_state.json" ]]; then
  hot_work_args+=(--state-file "kuaishou=$root/data/intel/hot_works_multiplatform_20260822/cookie_probe/kuaishou_playwright_state.json")
fi
if [[ -f "$data_root/intel/hot_works_multiplatform_20260822/cookie_probe/douyin_playwright_state.json" ]]; then
  hot_work_args+=(--state-file "douyin=$root/data/intel/hot_works_multiplatform_20260822/cookie_probe/douyin_playwright_state.json")
fi
if run_platform --config "$config_path" --db "$data_root/state.db" "${hot_work_args[@]}" > "$out/hot-works-result.json"; then
  notify "progress" "hot_work_strategy_refreshed"
else
  notify "action_required" "hot_work_strategy_refresh_failed; continuing_with_previous_pack"
fi
run_platform --config "$config_path" --db "$data_root/state.db" \
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
run_platform --config "$config_path" --db "$data_root/state.db" \
  overnight-plan --tasks "$out/prepared.json" --output "$out/plan.json" \
  --start-minute 0 --deadline-minute 290 --finalization-minutes 10 > "$out/plan-result.json"
notify "progress" "overnight_plan_complete"
run_platform --config "$config_path" --db "$data_root/state.db" \
  overnight-run --plan "$out/plan.json" --state "$out/state.json" --events "$out/events.jsonl" > "$out/result.json"
run_platform --config "$config_path" --db "$data_root/state.db" \
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
