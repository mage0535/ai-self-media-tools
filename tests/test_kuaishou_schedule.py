from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from content_platform.kuaishou_schedule import schedule_kuaishou, schedule_time


def _result(tmp_path):
    video = tmp_path / "render" / "final.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    return {"title": "猫咪为什么踩奶", "body": "正文", "platforms": ["kuaishou"], "draft_meta": {},
            "artifacts": [{"kind": "video", "path": str(video)}]}


def test_schedule_time_is_the_china_day_of_the_window():
    assert schedule_time(datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc)) == "2026-11-05 18:30"


def test_scheduled_only_after_the_wrapper_passes_and_packet_carries_the_schedule(tmp_path):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{\n  "ok": true\n}', stderr="")

    outcome = schedule_kuaishou({"job_id": "j1"}, _result(tmp_path), out_dir=tmp_path / "out",
                                now=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc), run=run)

    build, publish = calls
    assert build[0][build[0].index("--schedule") + 1] == "2026-11-05 18:30"
    assert publish[1]["env"]["CONTENT_PLATFORM_OPS_RUNNER"] == "1" and publish[1]["env"]["JOB_ID"] == "j1"
    assert "external/social-auto-upload" in publish[0][publish[0].index("--sau-dir") + 1]
    assert outcome["state"] == "published_pending_verification"


def test_failed_postcheck_blocks_with_the_wrapper_stage(tmp_path):
    def run(cmd, **kwargs):
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=2, stdout='log {"x": 1}\n{\n  "ok": false,\n  "stage": "preflight"\n}', stderr="")

    outcome = schedule_kuaishou({"job_id": "j1"}, _result(tmp_path), out_dir=tmp_path / "out",
                                now=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc), run=run)

    assert outcome == {"state": "blocked", "reason": "kuaishou_schedule: preflight", "evidence_dir": str(tmp_path / "out")}


def test_no_video_blocks_before_any_upload(tmp_path):
    outcome = schedule_kuaishou({"job_id": "j1"}, {"artifacts": []}, out_dir=tmp_path, now=datetime.now(timezone.utc),
                                run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert outcome["state"] == "blocked"
