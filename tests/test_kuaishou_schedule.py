import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from content_platform import kuaishou_publish_gates as gates
from content_platform.kuaishou_schedule import schedule_kuaishou, schedule_time

NOW = datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc)  # 00:30 CST on 11-05


def _scene(seed: int) -> Image.Image:
    """A textured photo-like frame: the body_visual gate rejects flat or solid backgrounds."""
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 215, size=(48, 27, 3), dtype=np.uint8)
    return Image.fromarray(base).resize((540, 960), Image.BICUBIC)


def _video(path: Path, frames: list[Image.Image]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        frame.save(path.parent / f"_f{index}.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1",
                    "-i", str(path.parent / "_f%d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", str(path)],
                   check=True)
    return path


def _cover(path: Path) -> Path:
    image = Image.new("RGB", (1080, 1920), (240, 120, 30))
    draw = ImageDraw.Draw(image)
    for y in range(0, 1920, 160):
        draw.rectangle([0, y, 1080, y + 60], fill=(20, 60, 160))
    draw.ellipse([240, 600, 840, 1200], fill=(250, 250, 250))
    image.save(path)
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    frames = [_scene(seed) for seed in range(6)]
    good = _video(root / "good" / "final.mp4", frames)
    solid = _video(root / "solid" / "final.mp4", [Image.new("RGB", (540, 960), (30, 30, 30))] * 6)
    return {"good": good, "solid": solid, "frame0": frames[0]}


def _task():
    return {"job_id": "j1", "platform": "kuaishou", "selection_mode": "trend_driven",
            "trend_candidate": {"title": "猫咪踩奶", "score": 0.8}, "trend_candidate_gate": {"passed": True},
            "brief": {"topic": "猫咪为什么踩奶", "content_blueprint": {"hook": "踩奶不是撒娇"}, "topic_decision": {"score": 0.8}}}


def _result(video: Path, cover: Path | None):
    artifacts = [{"kind": "video", "path": str(video)}]
    if cover:
        artifacts.append({"kind": "cover", "path": str(cover)})
    return {"title": "猫咪为什么踩奶", "body": "正文 #猫咪 说明", "platforms": ["kuaishou"], "draft_meta": {},
            "artifacts": artifacts}


def _copy(media, tmp_path, key="good", cover=True, cover_image=None):
    render = tmp_path / "render"
    render.mkdir()
    video = render / "final.mp4"
    video.write_bytes(media[key].read_bytes())
    cover_path = None
    if cover:
        cover_path = render / "cover.png"
        (cover_image.save(cover_path) if cover_image is not None else _cover(cover_path))
    return _result(video, cover_path)


class FakeRun:
    def __init__(self, publish_rc=0, stdout='{\n  "ok": true\n}'):
        self.calls, self.publish_rc, self.stdout = [], publish_rc, stdout

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if "--out" in cmd:
            Path(cmd[cmd.index("--out") + 1]).write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=self.publish_rc, stdout=self.stdout, stderr="")

    def publishes(self):
        return [cmd for cmd, _ in self.calls if any("kuaishou_publish_with_postcheck" in str(part) for part in cmd)]


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    flag = tmp_path / "kuaishou-autopublish.enabled"
    flag.write_text("", encoding="utf-8")
    monkeypatch.setenv("KUAISHOU_AUTOPUBLISH_FLAG", str(flag))
    return flag


def _log(out):
    return json.loads((out / "publish_log.json").read_text(encoding="utf-8"))


def test_schedule_time_is_the_china_day_of_the_window():
    assert schedule_time(NOW) == "2026-11-05 18:30"
    assert schedule_time(NOW, "20:05") == "2026-11-05 20:05"


def test_flag_defaults_to_the_etc_path(monkeypatch):
    monkeypatch.delenv("KUAISHOU_AUTOPUBLISH_FLAG", raising=False)
    assert str(gates.flag_path()) == "/etc/hermes/kuaishou-autopublish.enabled"


def test_all_gates_pass_schedules_once_with_cover_and_logs(media, tmp_path, enabled):
    run, out = FakeRun(), tmp_path / "out"
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path), out_dir=out, now=NOW, run=run)

    build = run.calls[0][0]
    assert build[build.index("--schedule") + 1] == "2026-11-05 18:30"
    assert "#" not in build[build.index("--desc") + 1]
    assert Path(build[build.index("--cover") + 1]).name == "cover.png"
    assert len(run.publishes()) == 1
    publish_env = run.calls[1][1]["env"]
    assert publish_env["CONTENT_PLATFORM_OPS_RUNNER"] == "1" and publish_env["JOB_ID"] == "j1"
    assert outcome["state"] == "published_pending_verification"
    log = _log(out)
    assert log["decision"] == "published_pending_verification"
    assert log["gates"]["ops"]["OPS_PASS"] is True and log["gates"]["body_visual"]["passed"] is True
    assert (out / "cover_evidence.json").is_file() and (out / "kuaishou_ops.json").is_file()
    assert len((tmp_path / "autopublish_ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_slot_schedule_hhmm_is_used(media, tmp_path, enabled):
    run = FakeRun()
    schedule_kuaishou(_task(), _copy(media, tmp_path), out_dir=tmp_path / "out", now=NOW, hhmm="20:05", run=run)
    build = run.calls[0][0]
    assert build[build.index("--schedule") + 1] == "2026-11-05 20:05"


@pytest.mark.parametrize("hhmm", ["25:00", "8:30", "00:40"])
def test_invalid_or_past_schedule_blocks(media, tmp_path, enabled, hhmm):
    run = FakeRun()
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path), out_dir=tmp_path / "out", now=NOW, hhmm=hhmm, run=run)
    assert outcome["state"] == "blocked" and run.calls == []


def test_missing_flag_blocks_before_anything(media, tmp_path, monkeypatch):
    monkeypatch.setenv("KUAISHOU_AUTOPUBLISH_FLAG", str(tmp_path / "absent.enabled"))
    run, out = FakeRun(), tmp_path / "out"
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path), out_dir=out, now=NOW, run=run)
    assert outcome["state"] == "blocked" and "kuaishou_autopublish_disabled" in outcome["reason"]
    assert run.calls == [] and _log(out)["decision"] == "blocked"


def test_body_visual_failure_blocks(media, tmp_path, enabled):
    run, out = FakeRun(), tmp_path / "out"
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path, key="solid"), out_dir=out, now=NOW, run=run)
    assert outcome["state"] == "blocked" and "BACKGROUND_EMPTY_OR_SOLID" in outcome["reason"]
    assert run.calls == []


def test_kf_freeze_record_blocks_even_with_good_pixels(media, tmp_path, enabled):
    run, result = FakeRun(), _copy(media, tmp_path)
    result["render_manifest"] = {"MOTION_FALLBACK": "kf_freeze"}
    outcome = schedule_kuaishou(_task(), result, out_dir=tmp_path / "out", now=NOW, run=run)
    assert "MOTION_FALLBACK_BLOCKS_QUALIFIED" in outcome["reason"] and run.calls == []


def test_missing_cover_blocks(media, tmp_path, enabled):
    run = FakeRun()
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path, cover=False), out_dir=tmp_path / "out", now=NOW, run=run)
    assert "COVER_MISSING" in outcome["reason"] and run.calls == []


def test_cover_that_is_a_body_frame_blocks(media, tmp_path, enabled):
    run, out = FakeRun(), tmp_path / "out"
    frame = media["frame0"].resize((1080, 1920))
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path, cover_image=frame), out_dir=out, now=NOW, run=run)
    assert "COVER_SCREENSHOT_FORBIDDEN" in outcome["reason"] and run.calls == []
    assert json.loads((out / "cover_evidence.json").read_text(encoding="utf-8"))["is_body_frame"] is True


@pytest.mark.parametrize("drop", ["heat", "strategy", "checklist"])
def test_ops_missing_any_part_blocks(media, tmp_path, enabled, drop):
    task = _task()
    if drop == "heat":
        task["trend_candidate_gate"] = {"passed": False}
    elif drop == "strategy":
        task["brief"].pop("content_blueprint")
    else:
        task["platform"] = "douyin"  # a checklist item fails: ops are Kuaishou-only
    run, out = FakeRun(), tmp_path / "out"
    outcome = schedule_kuaishou(task, _copy(media, tmp_path), out_dir=out, now=NOW, run=run)
    assert "KUAISHOU_OPS_INCOMPLETE" in outcome["reason"] and run.calls == []
    assert _log(out)["gates"]["ops"]["OPS_PASS"] is False


def test_ops_pass_is_computed_not_copied():
    ops = {"platform": "kuaishou", "heat": {}, "strategy": {"topic": "x"}, "checklist": [{"item": "a", "passed": True}],
           "OPS_PASS": True, "MAGIC_PASS": True}
    assert gates.ops_gate(ops)["OPS_PASS"] is False


def test_failed_postcheck_blocks_with_the_wrapper_stage(media, tmp_path, enabled):
    run = FakeRun(publish_rc=2, stdout='log {"x": 1}\n{\n  "ok": false,\n  "stage": "preflight"\n}')
    out = tmp_path / "out"
    outcome = schedule_kuaishou(_task(), _copy(media, tmp_path), out_dir=out, now=NOW, run=run)
    assert outcome == {"state": "blocked", "reason": "kuaishou_schedule: preflight", "evidence_dir": str(out)}
    assert _log(out)["decision"] == "blocked"


def test_no_video_blocks_before_any_upload(tmp_path, enabled):
    outcome = schedule_kuaishou({"job_id": "j1"}, {"artifacts": []}, out_dir=tmp_path / "out", now=NOW,
                                run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert outcome["state"] == "blocked"


def test_packet_video_path_reads_kuaishou_keys_only():
    from content_platform.media_quality import _packet_video_path

    assert _packet_video_path({"video_file": "/v.mp4"}, "kuaishou") == "/v.mp4"
    assert _packet_video_path({"file": "/v.mp4"}, "kuaishou") == "/v.mp4"
    assert _packet_video_path({"video_file": "/v.mp4"}, "douyin") == ""


def test_cancel_script_is_dry_run(tmp_path):
    from scripts.kuaishou_cancel_scheduled import main

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"decision": "published_pending_verification", "schedule_time": "2099-01-01 18:30",
                                  "title": "t"}) + "\n", encoding="utf-8")
    assert main(["--ledger", str(ledger)]) == 0
    assert main(["--ledger", str(ledger), "--confirm"]) == 3
