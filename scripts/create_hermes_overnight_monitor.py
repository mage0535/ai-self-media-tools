"""Create the read-only Hermes observer without shell-quoted cron arguments."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROMPT = """You are the read-only ai-self-media-tools overnight observer.
Report only state changes from the monitor source, events.jsonl, state.json,
result.json, workflow reports, and quality-gate reports. Report platform start,
source status, independent topic and growth signals, tool selection, generation,
rendering, gate, draft or handoff state, and real errors. Never modify code,
configuration, data, cookies, queues, cron, or systemd. Never start, stop, or
repeat the worker. Never approve, publish, bypass a gate, or use AiToEarn.
Manual channels may only be reported as handoff_ready. If blocked, failed, or
idle for over nine minutes, report the current state and reason. After 04:50
summarize only; do not request retries or new tasks. Do not interfere with the
05:00 morning report."""


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env_file = root / "secrets" / "notifications.env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.strip().partition("=")
            if separator and key == "AI_SELF_MEDIA_TELEGRAM_TARGET" and value.strip():
                os.environ.setdefault(key, value.strip().strip("'\""))
    target = os.environ.get("AI_SELF_MEDIA_TELEGRAM_TARGET", "").strip()
    if not target:
        raise SystemExit("AI_SELF_MEDIA_TELEGRAM_TARGET is required")
    existing = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, check=False)
    if existing.returncode == 0 and "AI自媒体夜间运行监控" in existing.stdout:
        return 0
    command = [
        "hermes", "cron", "create", "*/3 0-4 * * *", PROMPT,
        "--name", "AI自媒体夜间运行监控",
        "--deliver", target,
        "--monitor-script", "monitor_overnight_batch.sh",
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
