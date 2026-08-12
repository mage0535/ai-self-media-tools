"""Create the read-only Hermes observer without shell-quoted cron arguments."""

from __future__ import annotations

import os
import subprocess
import sys


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
    target = os.environ.get("AI_SELF_MEDIA_TELEGRAM_TARGET", "").strip()
    if not target:
        raise SystemExit("AI_SELF_MEDIA_TELEGRAM_TARGET is required")
    command = [
        "hermes", "cron", "create", "*/3 0-4 * * *", PROMPT,
        "--name", "AI自媒体夜间运行监控",
        "--deliver", target,
        "--monitor-script", "monitor_overnight_batch.sh",
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
