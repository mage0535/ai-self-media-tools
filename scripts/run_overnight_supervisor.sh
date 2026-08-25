#!/usr/bin/env bash
# Independent heartbeat watcher for the overnight batch. It never republishes.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
release_root=$(readlink -f -- "$root")
if ! [[ -n "$release_root" && -d "$release_root" ]]; then
  printf '%s\n' 'CONTENT_PLATFORM_HOME must resolve to a non-empty existing release root' >&2
  exit 1
fi
data_root="${CONTENT_PLATFORM_DATA_DIR:-$(dirname -- "$release_root")/data}"
secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:-$release_root/secrets}"
config_path="${CONTENT_PLATFORM_CONFIG:-$release_root/config.json}"
metadata_path="${CONTENT_PLATFORM_RELEASE_METADATA:-$release_root/release-metadata.json}"
attestation_path="${CONTENT_PLATFORM_RELEASE_ATTESTATION:-$data_root/release-attestations/$(basename -- "$release_root").sha256}"
signing_key="${CONTENT_PLATFORM_RELEASE_SIGNING_KEY:-$secrets_root/release-signing.key}"
day="$(date +%F)"
out="$data_root/overnight/$day"
state="$out/state.json"
heartbeat="$out/heartbeat.json"
report="$out/supervisor-report.json"

install -d "$data_root"
exec 9>"$data_root/runtime-release.lock"
flock -s 9
CONTENT_PLATFORM_CODE_ROOT="$release_root" \
  python3 "$release_root/scripts/runtime_release_audit.py" --verify-metadata \
  --metadata-path "$metadata_path" --attestation-path "$attestation_path" \
  --signing-key "$signing_key" \
  --release-root "$release_root"

[[ -f "$state" ]] || exit 0

notify() {
  "$release_root/scripts/notify_hermes_progress.sh" "overnight-supervisor" "$1" "${2:-}" || true
}

run_platform() {
  PYTHONPATH="$release_root${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform "$@"
}

# Always reconcile terminal snapshots too: state vocabulary changes must not
# wait for a future stale-heartbeat incident before becoming operator-visible.
run_platform --config "$config_path" --db "$data_root/state.db" \
  overnight-sync-state --state "$state" --output "$out/acceptance_summary.json" > "$out/supervisor-sync.json"

run_platform --config "$config_path" --db "$data_root/state.db" \
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
run_platform --config "$config_path" --db "$data_root/state.db" recover > "$out/supervisor-recover.json" || true
if [[ -f "$out/plan.json" ]]; then
  notify "progress" "automatic_recovery_started; see $report"
  if run_platform --config "$config_path" --db "$data_root/state.db" \
    overnight-run --plan "$out/plan.json" --state "$state" --events "$out/events.jsonl" \
    > "$out/supervisor-recovery-result.json"; then
    run_platform --config "$config_path" --db "$data_root/state.db" \
      overnight-sync-state --state "$state" --output "$out/acceptance_summary.json" \
      > "$out/supervisor-recovery-sync.json"
    notify "resolved" "automatic_recovery_completed; see $out/supervisor-recovery-result.json"
  else
    notify "action_required" "automatic_recovery_failed; see $out/supervisor-recovery-result.json"
  fi
else
  notify "action_required" "heartbeat_stale_reconciled_without_plan; see $report"
fi
