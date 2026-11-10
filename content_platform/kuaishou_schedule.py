"""Scheduled Kuaishou auto-post for an overnight slot whose action is ``schedule_publish`` (MED26).

The owner runs Kuaishou as an automatic scheduled post. Publication stays explicit: only a slot that names
this action reaches it, and success needs the management-page postcheck of
``scripts/kuaishou_publish_with_postcheck.py`` (exact schedule time, or under review), never uploader output.

Owner 11-10 CST: Kuaishou is the only live exception (CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH stays 0 for
everything else, and this path never reads it). Before any packet is built, ``kuaishou_publish_gates`` must
pass: kill-switch flag, body_visual five codes, independent cover, and program-checked Kuaishou ops
(OPS_PASS). Any failure blocks with one ``publish_log.json`` report; every call appends the ledger.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SAU_DIR = ROOT / "external" / "social-auto-upload"
DEFAULT_SCHEDULE = "18:30"  # CST; the most used past Kuaishou schedule slot (09-13 packets).
# The post must still be in the future when the wrapper sets it; the window ends by 06:00 CST at the latest.
MIN_LEAD_MINUTES = 60


def schedule_time(now: datetime, hhmm: str = DEFAULT_SCHEDULE) -> str:
    """Same China-time day as the overnight window (00:00-01:15 CST), at ``hhmm``."""
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    return f"{local:%Y-%m-%d} {hhmm}"


def valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value or "")))


def _last_json(text: str) -> dict[str, Any]:
    """The wrapper ends with one indented ``{"ok": ...}`` report; earlier output may hold other JSON."""
    start = text.rfind('{\n  "ok"')
    try:
        value = json.loads(text[start:]) if start >= 0 else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _video_path(result: dict[str, Any]) -> Path | None:
    for item in result.get("artifacts") or []:
        if isinstance(item, dict) and item.get("kind") == "video" and Path(str(item.get("path") or "")).is_file():
            return Path(item["path"])
    return None


def schedule_kuaishou(task: dict[str, Any], result: dict[str, Any], *, out_dir: Path, now: datetime,
                      hhmm: str | None = None, run=subprocess.run) -> dict[str, str]:
    """Return the task outcome: ``published_pending_verification`` after a passed postcheck, else ``blocked``."""
    from . import kuaishou_publish_gates as gates
    from .formatters import format_for_platform

    hhmm = hhmm or DEFAULT_SCHEDULE
    log: dict[str, Any] = {"job_id": str(task.get("job_id") or ""), "platform": "kuaishou", "gates": {}}

    def blocked(reason: str) -> dict[str, str]:
        gates.write_publish_log(out_dir, {**log, "decision": "blocked", "reason": reason})
        return {"state": "blocked", "reason": f"kuaishou_schedule: {reason}"[:300], "evidence_dir": str(out_dir)}

    log["gates"]["kill_switch"] = gates.kill_switch_gate()
    if not log["gates"]["kill_switch"]["passed"]:
        return blocked("kuaishou_autopublish_disabled")
    video = _video_path(result)
    if video is None:
        return blocked("no rendered video artifact")
    render_dir = video.parent
    log["video_sha256"] = gates.sha256_file(video)
    if not valid_hhmm(hhmm):
        return blocked(f"schedule_hhmm_invalid:{hhmm}")
    when = schedule_time(now, hhmm)
    log["schedule_time"] = when
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if (datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Shanghai")) - local_now).total_seconds() < MIN_LEAD_MINUTES * 60:
        return blocked(f"schedule_time_too_close:{when}")
    formatted = format_for_platform(result, "kuaishou")
    log["title"] = str(formatted.get("title") or result.get("title") or "")[:30]
    out_dir.mkdir(parents=True, exist_ok=True)
    ops = gates.build_kuaishou_ops({**task, "platform": task.get("platform") or "kuaishou"}, formatted, now=now)
    (out_dir / "kuaishou_ops.json").write_text(json.dumps(ops, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log["gates"]["ops"] = gates.ops_gate(ops)
    log["gates"]["body_visual"] = gates.body_visual_publish_gate(video, result)
    log["gates"]["cover"] = gates.cover_gate(result, video, render_dir, out_dir)
    log["cover_sha256"] = log["gates"]["cover"].get("cover_sha256", "")
    failed = [name for name in ("body_visual", "cover", "ops") if not log["gates"][name]["passed"]]
    if failed:
        codes = list(log["gates"]["body_visual"]["failed_codes"])
        codes += [log["gates"][name]["code"] for name in ("cover", "ops") if log["gates"][name].get("code")]
        return blocked("publish gates failed: " + ",".join(codes))
    packet = out_dir / "kuaishou_packet.json"
    build = run([sys.executable, str(ROOT / "scripts" / "build_kuaishou_packet.py"), "--render-dir", str(render_dir),
                 "--title", log["title"],
                 # The wrapper uploads the description without hashtags and its postcheck compares the packet's
                 # description exactly, so the packet must not carry them either.
                 "--desc", " ".join(re.sub(r"#[^\s#]+", "", str(formatted.get("caption") or "")).split())[:500],
                 "--tags", ",".join(str(tag).lstrip("#") for tag in (formatted.get("hashtags") or [])[:3]),
                 "--cover", log["gates"]["cover"]["cover_path"],
                 "--schedule", when, "--out", str(packet)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    if build.returncode != 0 or not packet.is_file():
        return blocked("packet build failed: " + (build.stderr or build.stdout)[-300:])
    env = {**os.environ, "CONTENT_PLATFORM_OPS_RUNNER": "1", "JOB_ID": str(task.get("job_id") or ""),
           "WORKFLOW_ID": f"wf_{task.get('job_id')}", "RUN_ID": f"overnight-{now:%Y%m%dT%H%M%SZ}"}
    publish = run([sys.executable, str(ROOT / "scripts" / "kuaishou_publish_with_postcheck.py"), str(packet),
                   "--sau-dir", str(SAU_DIR), "--sau-python", str(SAU_DIR / "venv" / "bin" / "python"),
                   "--out-dir", str(out_dir / "publish")],
                  cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1500)
    report = _last_json(publish.stdout)
    if publish.returncode == 0:  # The wrapper exits 0 only after the management-page postcheck passed.
        gates.write_publish_log(out_dir, {**log, "decision": "published_pending_verification",
                                          "reason": "postcheck passed", "postcheck": report})
        return {"state": "published_pending_verification", "reason": f"scheduled {when} CST; postcheck passed",
                "schedule_time": when, "evidence_dir": str(out_dir)}
    stage = str(report.get("stage") or report.get("error") or f"exit {publish.returncode}")
    log["postcheck"] = report
    return blocked(stage)
