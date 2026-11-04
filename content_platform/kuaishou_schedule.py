"""Scheduled Kuaishou auto-post for an overnight slot whose action is ``schedule_publish`` (MED26).

The owner runs Kuaishou as an automatic scheduled post. Publication stays explicit: only a slot that names
this action reaches it, and success needs the management-page postcheck of
``scripts/kuaishou_publish_with_postcheck.py`` (exact schedule time, or under review), never uploader output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SAU_DIR = ROOT / "external" / "social-auto-upload"
DEFAULT_SCHEDULE = "18:30"  # CST; the most used past Kuaishou schedule slot (09-13 packets).


def schedule_time(now: datetime, hhmm: str = DEFAULT_SCHEDULE) -> str:
    """Same China-time day as the overnight window (00:00-01:15 CST), at ``hhmm``."""
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    return f"{local:%Y-%m-%d} {hhmm}"


def _video_dir(result: dict[str, Any]) -> Path | None:
    for item in result.get("artifacts") or []:
        if isinstance(item, dict) and item.get("kind") == "video" and Path(str(item.get("path") or "")).is_file():
            return Path(item["path"]).parent
    return None


def _last_json(text: str) -> dict[str, Any]:
    """The wrapper ends with one indented ``{"ok": ...}`` report; earlier output may hold other JSON."""
    start = text.rfind('{\n  "ok"')
    try:
        value = json.loads(text[start:]) if start >= 0 else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def schedule_kuaishou(task: dict[str, Any], result: dict[str, Any], *, out_dir: Path, now: datetime,
                      hhmm: str = DEFAULT_SCHEDULE, run=subprocess.run) -> dict[str, str]:
    """Return the task outcome: ``published_pending_verification`` after a passed postcheck, else ``blocked``."""
    from .formatters import format_for_platform

    render_dir = _video_dir(result)
    if render_dir is None:
        return {"state": "blocked", "reason": "kuaishou_schedule: no rendered video artifact"}
    formatted = format_for_platform(result, "kuaishou")
    out_dir.mkdir(parents=True, exist_ok=True)
    packet = out_dir / "kuaishou_packet.json"
    when = schedule_time(now, hhmm)
    build = run([sys.executable, str(ROOT / "scripts" / "build_kuaishou_packet.py"), "--render-dir", str(render_dir),
                 "--title", str(formatted.get("title") or result.get("title") or "")[:30],
                 "--desc", str(formatted.get("caption") or formatted.get("description") or "")[:500],
                 "--tags", ",".join(str(tag).lstrip("#") for tag in (formatted.get("hashtags") or [])[:3]),
                 "--schedule", when, "--out", str(packet)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    if build.returncode != 0 or not packet.is_file():
        return {"state": "blocked", "reason": "kuaishou_schedule: packet build failed: " + (build.stderr or build.stdout)[-300:]}
    env = {**os.environ, "CONTENT_PLATFORM_OPS_RUNNER": "1", "JOB_ID": str(task.get("job_id") or ""),
           "WORKFLOW_ID": f"wf_{task.get('job_id')}", "RUN_ID": f"overnight-{now:%Y%m%dT%H%M%SZ}"}
    publish = run([sys.executable, str(ROOT / "scripts" / "kuaishou_publish_with_postcheck.py"), str(packet),
                   "--sau-dir", str(SAU_DIR), "--sau-python", str(SAU_DIR / "venv" / "bin" / "python"),
                   "--out-dir", str(out_dir / "publish")],
                  cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1500)
    report = _last_json(publish.stdout)
    if publish.returncode == 0:  # The wrapper exits 0 only after the management-page postcheck passed.
        return {"state": "published_pending_verification", "reason": f"scheduled {when} CST; postcheck passed",
                "schedule_time": when, "evidence_dir": str(out_dir)}
    stage = str(report.get("stage") or report.get("error") or f"exit {publish.returncode}")
    return {"state": "blocked", "reason": f"kuaishou_schedule: {stage}"[:300], "evidence_dir": str(out_dir)}
