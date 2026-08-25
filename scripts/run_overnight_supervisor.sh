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
secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:-$(dirname -- "$release_root")/secrets}"
config_path="${CONTENT_PLATFORM_CONFIG:-$release_root/config.json}"
metadata_path="${CONTENT_PLATFORM_RELEASE_METADATA:-$release_root/release-metadata.json}"
attestation_path="${CONTENT_PLATFORM_RELEASE_ATTESTATION:-$data_root/release-attestations/$(basename -- "$release_root").sha256}"
signing_key="${CONTENT_PLATFORM_RELEASE_SIGNING_KEY:-$secrets_root/release-signing.key}"
trusted_secrets_root="$secrets_root"
day="$(date +%F)"
out="$data_root/overnight/$day"
state="$out/state.json"
heartbeat="$out/heartbeat.json"
report="$out/supervisor-report.json"

install -d "$data_root"
exec 8>"$data_root/runtime-release.lock"
flock -s 8
exec 9>"$data_root/overnight-supervisor.lock"
if ! flock -n 9; then
  printf '%s\n' '{"status":"rejected","reason":"another overnight supervisor is live"}' >&2
  exit 75
fi
CONTENT_PLATFORM_CODE_ROOT="$release_root" \
  python3 "$release_root/scripts/runtime_release_audit.py" --verify-metadata \
  --metadata-path "$metadata_path" --attestation-path "$attestation_path" \
  --signing-key "$signing_key" \
  --trusted-secrets-root "$trusted_secrets_root" \
  --release-root "$release_root"

[[ -f "$state" ]] || exit 0

notify() {
  "$release_root/scripts/notify_hermes_progress.sh" "overnight-supervisor" "$1" "${2:-}" || true
}

report_events() {
  "$release_root/scripts/run_overnight_reporter.sh" "$out" "$out/events.jsonl" "$out/reporter.cursor.json" || true
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
report_events

status="$(python3 - "$report" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", "missing"))
PY
)"

if [[ "$status" != "stale" ]]; then
  exit 0
fi

recovery_authorized="$(python3 - "$report" <<'PY'
import json
import sys
print(str(json.load(open(sys.argv[1], encoding="utf-8")).get("recovery_authorized", False)).lower())
PY
)"

if [[ "$recovery_authorized" != "true" ]]; then
  recovery_pending="$out/recovery-pending.json"
  python3 - "$recovery_pending" "$state" "$report" "$out/plan.json" <<'PY'
import json
import sys
from pathlib import Path

output, state, report, plan = map(Path, sys.argv[1:])
output.write_text(
    json.dumps(
        {
            "status": "recovery_pending",
            "reason": "stale_heartbeat_owner_proof_required",
            "state": str(state),
            "supervisor_report": str(report),
            "plan": str(plan) if plan.exists() else None,
            "automatic_execution": False,
            "delivery": False,
        },
        ensure_ascii=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
  report_events
  notify "action_required" "recovery_pending; live owner or missing proof; automatic execution and delivery disabled; see $recovery_pending"
  exit 0
fi

# A stale service may own browser or publisher state. Recover only durable
# leases and reconcile facts; a new batch is never started from this watcher.
run_platform --config "$config_path" --db "$data_root/state.db" recover > "$out/supervisor-recover.json" || true
report_events
recovery_pending="$out/recovery-pending.json"
python3 - "$recovery_pending" "$state" "$report" "$out/supervisor-recover.json" "$out/plan.json" <<'PY'
import json
import sys
from pathlib import Path

output, state, report, lease_recovery, plan = map(Path, sys.argv[1:])
output.write_text(
    json.dumps(
        {
            "status": "recovery_pending",
            "reason": "stale_heartbeat",
            "state": str(state),
            "supervisor_report": str(report),
            "lease_recovery": str(lease_recovery),
            "plan": str(plan) if plan.exists() else None,
            "automatic_execution": False,
            "delivery": False,
        },
        ensure_ascii=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
notify "action_required" "recovery_pending; automatic execution and delivery disabled; see $recovery_pending and $report"
