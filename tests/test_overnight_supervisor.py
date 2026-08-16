import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_platform.overnight_supervisor import inspect_batch_health


def test_supervisor_marks_a_running_batch_with_a_stale_heartbeat_recoverable(tmp_path: Path):
    now = datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)
    state_path = tmp_path / "state.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    state_path.write_text(json.dumps({"status": "running", "tasks": [{"platform": "kuaishou", "state": "running"}]}), encoding="utf-8")
    heartbeat_path.write_text(json.dumps({"at": (now - timedelta(minutes=31)).isoformat(), "event": "platform_started", "platform": "kuaishou"}), encoding="utf-8")

    report = inspect_batch_health(state_path, heartbeat_path, now=now, stale_after_seconds=1800)

    assert report["status"] == "stale"
    assert report["recovery_required"] is True
    assert report["platform"] == "kuaishou"


def test_supervisor_accepts_a_fresh_terminal_batch(tmp_path: Path):
    now = datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)
    state_path = tmp_path / "state.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    state_path.write_text(json.dumps({"status": "completed", "tasks": [{"platform": "twitter", "state": "published_verified"}]}), encoding="utf-8")
    heartbeat_path.write_text(json.dumps({"at": now.isoformat(), "event": "platform_finished", "platform": "twitter"}), encoding="utf-8")

    report = inspect_batch_health(state_path, heartbeat_path, now=now)

    assert report["status"] == "terminal"
    assert report["recovery_required"] is False
