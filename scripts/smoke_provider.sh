#!/usr/bin/env bash
# Validate the configured Hermes generation route before an overnight batch.
set -euo pipefail

config_path="${1:?config path is required}"
root="$(cd "$(dirname "$config_path")" && pwd)"

readarray -t settings < <(python3 - "$config_path" <<'PY'
import json
import sys

generator = json.load(open(sys.argv[1], encoding="utf-8")).get("generator", {})
for key in ("hermes_command", "hermes_provider", "hermes_model"):
    print(str(generator.get(key) or ""))
PY
)
command="${settings[0]:-hermes}"
provider="${settings[1]:-}"
model="${settings[2]:-}"

[[ -n "$provider" && -n "$model" ]] || {
  echo "generator hermes_provider and hermes_model must be configured" >&2
  exit 2
}

output="$(env -i HOME="$HOME" PATH="$PATH" PYTHONPATH="$root" "$command" --provider "$provider" --model "$model" -z 'Return only JSON: {"title":"provider smoke","body":"provider smoke"}' --cli)"
python3 - "$output" <<'PY'
import json
import re
import sys

text = sys.argv[1].strip()
if re.match(r"^HTTP\s+(401|403|429|5\d{2})\b", text, flags=re.I):
    raise SystemExit("provider returned an HTTP failure")
try:
    payload = json.loads(text)
except json.JSONDecodeError as exc:
    raise SystemExit("provider returned invalid JSON") from exc
if not payload.get("title") or not payload.get("body"):
    raise SystemExit("provider JSON misses title or body")
PY
