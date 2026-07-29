#!/usr/bin/env python3
"""Run the daily content workflow once per configured publisher.

The systemd timer uses this file as the only daily entrypoint. It intentionally
creates platform-scoped jobs instead of one all-platform job, so each channel gets
its own operation analysis, generation context, quality gate, and history check.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from content_platform.cli import main


ROOT = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
CONFIG = ROOT / "config.json"
DB = ROOT / "data" / "state.db"


def configured_platforms() -> list[str]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    return list(config.get("publishers", {}).get("platforms", {}).keys())


def build_platform_argv(platform: str, *, refresh: bool) -> list[str]:
    limit = os.environ.get("CONTENT_PLATFORM_DAILY_PER_PLATFORM_LIMIT", "1")
    profile = os.environ.get("CONTENT_PLATFORM_DAILY_PROFILE", "default")
    argv = [
        "--config", str(CONFIG),
        "--db", str(DB),
        "auto",
        "--limit", str(limit),
        "--profile", profile,
        "--platform", platform,
    ]
    if refresh:
        argv.append("--refresh")
    return argv


def run_all() -> dict:
    platforms = configured_platforms()
    results = []
    refresh_each = os.environ.get("CONTENT_PLATFORM_DAILY_REFRESH_EACH", "0") == "1"
    for index, platform in enumerate(platforms):
        refresh = refresh_each or index == 0
        print(json.dumps({"event": "platform_start", "platform": platform, "refresh": refresh}, ensure_ascii=False), flush=True)
        try:
            result = main(build_platform_argv(platform, refresh=refresh))
            results.append({"platform": platform, "ok": True, "result": result})
            print(json.dumps({"event": "platform_done", "platform": platform, "ok": True}, ensure_ascii=False), flush=True)
        except Exception as exc:  # keep the daily run moving while preserving evidence.
            results.append({"platform": platform, "ok": False, "error": str(exc)[:500]})
            print(json.dumps({"event": "platform_failed", "platform": platform, "ok": False, "error": str(exc)[:500]}, ensure_ascii=False), flush=True)
    return {"ok": all(item["ok"] for item in results), "platform_count": len(platforms), "results": results}


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))
