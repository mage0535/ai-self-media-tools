#!/usr/bin/env bash
# Refreshes only explicitly configured, legally obtained article-level exports.
set -euo pipefail

ROOT="${WECHAT_BLOWUP_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
DATA_DIR="${CONTENT_PLATFORM_DATA_DIR:-$ROOT/data}"
CONFIG="${CONTENT_PLATFORM_CONFIG:-$ROOT/config.json}"
DB="${CONTENT_PLATFORM_DB:-$DATA_DIR/state.db}"
SOURCES="${WECHAT_BLOWUP_SOURCES_FILE:-$DATA_DIR/../config/wechat_blowup_sources.json}"
OUTPUT="${WECHAT_BLOWUP_OUTPUT_FILE:-$DATA_DIR/intel/wechat_blowup_intelligence_latest.json}"

cd "$ROOT"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m content_platform.cli \
  --config "$CONFIG" \
  --db "$DB" \
  wechat-blowup-refresh \
  --sources "$SOURCES" \
  --output "$OUTPUT"
