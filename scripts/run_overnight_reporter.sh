#!/usr/bin/env bash
# Independent, cursor-backed business reporter for the overnight event stream.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
release_root=$(readlink -f -- "$root")
if ! [[ -n "$release_root" && -d "$release_root" ]]; then
  printf '%s\n' 'CONTENT_PLATFORM_HOME must resolve to a non-empty existing release root' >&2
  exit 1
fi

data_root="${CONTENT_PLATFORM_DATA_DIR:-$(dirname -- "$release_root")/data}"
out="${1:-$data_root/overnight/$(date +%F)}"
events="${2:-$out/events.jsonl}"
cursor="${3:-$out/reporter.cursor.json}"
[[ -f "$events" ]] || exit 0

exec 8>"$cursor.lock"
flock -n 8 || exit 75

while IFS= read -r message; do
  [[ -n "$message" ]] || continue
  "$release_root/scripts/notify_hermes_progress.sh" "overnight-reporter" "business_update" "$message" || true
done < <(
  PYTHONPATH="$release_root${PYTHONPATH:+:$PYTHONPATH}" \
    python3 "$release_root/scripts/overnight_reporter.py" --events "$events" --cursor "$cursor"
)
