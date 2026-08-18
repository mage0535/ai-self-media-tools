#!/usr/bin/env bash
# Send operational status only when a private Hermes target is configured.
set -euo pipefail

component="${1:?component is required}"
state="${2:?state is required}"
detail="${3:-}"
target="${AI_SELF_MEDIA_HERMES_TARGET:-}"

[[ -n "$target" ]] || exit 0
message="[ai-self-media:${component}] ${state}"
[[ -n "$detail" ]] && message+=$'\n'"detail=${detail}"
hermes send --to "$target" --quiet "$message" || exit 0
