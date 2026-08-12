# Read-Only Acceptance Commands

Run these commands from the project root. They do not publish content, modify
credentials, or clear runtime data.

```bash
python3 -m pytest -q --tb=short
python3 -m compileall -q content_platform scripts
python3 -m content_platform.cli project-audit
```

For a rendered original-video package, inspect the manifest rather than a
planned tool list. Acceptance requires all of the following:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path("<render-output>/video_toolchain_runner_manifest.json")
m = json.loads(p.read_text(encoding="utf-8"))
print({
  "status": m.get("status"),
  "motion_frames": (m.get("motion_evidence") or {}).get("unique_frame_count"),
  "segment_moves": len(((m.get("segment_motion_evidence") or {}).get("segments") or [])),
  "shotcraft_timeline": len(((m.get("shotcraft_motion_plan") or {}).get("timeline") or [])),
})
PY
```

The package passes only when `status` is `rendered`, `motion_frames` is at
least 2, and every segment evidence item contains both `move_id` and `profile`.
Manual-handoff deliveries must remain `handoff_ready`; they are not evidence
of a completed public post.
