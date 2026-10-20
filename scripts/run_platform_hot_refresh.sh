#!/usr/bin/env bash
# Refresh public, auditable platform hot-work evidence without credentials.
set -euo pipefail

ROOT="${CONTENT_PLATFORM_CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
DATA_DIR="${CONTENT_PLATFORM_DATA_DIR:-$ROOT/data}"
CONFIG_DIR="${CONTENT_PLATFORM_SHARED_CONFIG_DIR:-$ROOT/config}"
DB="${CONTENT_PLATFORM_DB:-$DATA_DIR/state.db}"
SOURCES="$CONFIG_DIR/platform_hot_evidence_sources.json"
EVIDENCE="$DATA_DIR/intel/platform_hot_evidence_latest.json"
HISTORY_DIR="$DATA_DIR/intel/platform_hot_evidence_history"
HISTORY_INDEX="$DATA_DIR/intel/platform_hot_evidence_history_index.jsonl"
OUTPUT_DIR="$DATA_DIR/intel/hot_works_bilibili_latest"

cd "$ROOT"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$CONFIG_DIR/real_world_ai_implementation_v1.json" "$SOURCES" "$CONFIG_DIR/channel_content_rulebook.json" <<'PY'
import json
import sys
from pathlib import Path

policy_path, sources_path, rulebook_path = map(Path, sys.argv[1:4])
policy = json.loads(policy_path.read_text(encoding="utf-8"))
sources = json.loads(sources_path.read_text(encoding="utf-8"))
rulebook_text = rulebook_path.read_text(encoding="utf-8")
if policy.get("policy_profile") != "real_world_ai_implementation_v1":
    raise SystemExit("canonical real-world AI policy profile missing")
if not str(policy.get("policy_revision") or "").strip():
    raise SystemExit("canonical real-world AI policy revision missing")
if sources.get("query_policy_profile") != policy.get("policy_profile"):
    raise SystemExit("hot-evidence source config is not bound to the canonical AI policy")
if sources.get("query_source") != "content_platform.real_world_ai_policy.build_discovery_queries":
    raise SystemExit("hot-evidence source config is not using the canonical query builder")
legacy = (
    "ai_efficiency_open_source",
    "international_ai_efficiency",
    "ai_tool_microcase",
    "open_source_project_short",
    "automation_workflow_short",
)
found = [marker for marker in legacy if marker in rulebook_text]
if found:
    raise SystemExit(f"legacy AI lane markers remain in active rulebook: {found}")
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform.cli \
  --db "$DB" hot-evidence-collect \
  --source-config "$SOURCES" --output "$EVIDENCE"
mkdir -p "$HISTORY_DIR"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$EVIDENCE" "$HISTORY_DIR" "$HISTORY_INDEX" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

source, history_dir, index = map(Path, sys.argv[1:])
payload = source.read_bytes()
parsed = json.loads(payload)
observed_at = str(parsed.get("observed_at") or "")
if not observed_at.endswith(("Z", "+00:00")):
    raise SystemExit("refusing to archive evidence without an aware observed_at timestamp")
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
target = history_dir / f"platform_hot_evidence_{stamp}.json"
tmp = target.with_suffix(".tmp")
tmp.write_bytes(payload)
os.replace(tmp, target)
entry = {"observed_at": observed_at, "archived_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "path": str(target), "sha256": hashlib.sha256(payload).hexdigest()}
with index.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -m content_platform.cli \
  --db "$DB" hot-works-collect \
  --skip-live --hot-evidence-file "$EVIDENCE" --output-dir "$OUTPUT_DIR"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$EVIDENCE" "$DATA_DIR/intel/public_work_breakdown_latest.json" <<'PY'
import json
import sys
from pathlib import Path
from content_platform.public_work_breakdown import build_public_work_breakdowns

source, output = map(Path, sys.argv[1:3])
bundle = json.loads(source.read_text(encoding="utf-8"))
report = build_public_work_breakdowns(bundle)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": report["status"], "output": str(output), **report["summary"]}, ensure_ascii=False))
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$EVIDENCE" "$DATA_DIR/intel/platform_intelligence_runtime_latest.json" <<'PY'
import json
import sys
from pathlib import Path
from content_platform.platform_intelligence_status import build_platform_intelligence_runtime_snapshot

source, output = map(Path, sys.argv[1:3])
bundle = json.loads(source.read_text(encoding="utf-8"))
snapshot = build_platform_intelligence_runtime_snapshot(bundle=bundle)
output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$EVIDENCE" "$DATA_DIR/intel/dual_lane_work_plans_latest.json" <<'PY'
import json
import sys
from pathlib import Path
from content_platform.dual_lane_planning_run import build_dual_lane_work_plans

source, output = map(Path, sys.argv[1:3])
bundle = json.loads(source.read_text(encoding="utf-8"))
plans = build_dual_lane_work_plans(bundle, lane="real_world_ai_implementation")
output.write_text(json.dumps(plans, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$HISTORY_INDEX" "$CONFIG_DIR/real_world_ai_implementation_v1.json" "$DATA_DIR/intel/platform_intelligence_eligibility_latest.json" <<'PY'
import json
import sys
from pathlib import Path
from content_platform.platform_intelligence_state import evaluate_platform_history

index, profile_path, output = map(Path, sys.argv[1:4])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
result = {
    "version": "platform_intelligence_eligibility_snapshot_v1",
    "policy_profile": profile.get("policy_profile"),
    "platforms": {
        platform: evaluate_platform_history(
            platform=platform,
            lane="real_world_ai_implementation",
            history_index=index,
        )
        for platform in profile.get("platforms") or []
    },
}
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$DATA_DIR/intel/learning_registry.json" "$DATA_DIR/intel/learning_runtime_latest.json" <<'PY'
import json
import sys
from pathlib import Path
from content_platform.learning_runtime import build_learning_runtime

registry, output = map(Path, sys.argv[1:3])
runtime = build_learning_runtime(registry)
output.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

