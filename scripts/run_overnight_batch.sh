#!/usr/bin/env bash
# A systemd-safe entrypoint. Keep scheduling policy out of a quoted unit line.
set -euo pipefail

root="${CONTENT_PLATFORM_HOME:?CONTENT_PLATFORM_HOME is required}"
bin="${CONTENT_PLATFORM_BIN:?CONTENT_PLATFORM_BIN is required}"
day="$(date +%F)"
out="$root/data/overnight/$day"
slots="$root/secrets/overnight-slots.json"
mkdir -p "$out"

# Persistent timers may fire after a reboot. Do not turn a missed midnight run
# into morning contention; only the planned midnight admission window is valid.
hhmm="$(date +%H%M)"
if (( 10#$hhmm > 15 )); then
  printf '%s\n' '{"status":"no_run","reason":"missed midnight start window"}' > "$out/result.json"
  exit 0
fi

if [[ ! -f "$slots" ]]; then
  printf '%s\n' '{"status":"no_slots"}' > "$out/result.json"
  exit 0
fi

"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-prepare --slots "$slots" --output "$out/prepared.json" --refresh > "$out/prepare-result.json"
"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-plan --tasks "$out/prepared.json" --output "$out/plan.json" \
  --start-minute 0 --deadline-minute 290 --finalization-minutes 10 > "$out/plan-result.json"
"$bin" --config "$root/config.json" --db "$root/data/state.db" \
  overnight-run --plan "$out/plan.json" --state "$out/state.json" --events "$out/events.jsonl" > "$out/result.json"
