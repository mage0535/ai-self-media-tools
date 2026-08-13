# Read-Only Acceptance Commands

Run these commands from the project root. They do not publish content, modify
credentials, or clear runtime data.

```bash
python3 -m pytest -q --tb=short
python3 -m compileall -q content_platform scripts
python3 -m content_platform.cli project-audit
```

For the quality-orchestration contracts, use the real CLI entries rather than
an inferred flag name:

```bash
python3 scripts/check_platform_topic_independence.py "$(date +%Y%m%d)" --lookback-days 7 --strict --platforms zhihu,juejin
python3 scripts/content_quality_gate.py --check-depth --data '{"version":"content_depth_plan_v1","title":"Example","actions":["baseline","measure","record"],"evidence":["measured example"],"knowledge_points":["baseline","measure","record"],"case_or_demo":"measured example","steps":["baseline","measure","record"],"counterexample":"generic advice","takeaway":"record the result","interaction_prompt":"Which step first?","continuation_claimed":false,"series_plan":{}}'
python3 scripts/pre_render_gate.py --video-dir <render-output> --require-scene-manifest
```

The topic gate permits a naturally overlapping direction only when both
platform packages show eight attempted sources and five successful sources, platform-internal evidence, a
platform signal, and a platform-specific adaptation reason. It does not permit
copying a shared topic merely because the titles differ.

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
It must also include `<render-output>/scene_manifest.json`; that file is a
projection of `visual_recipe.scene_asset_match`, not a separate plan.
Manual-handoff deliveries must remain `handoff_ready`; they are not evidence
of a completed public post.
