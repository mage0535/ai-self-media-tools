import json
from pathlib import Path


def _write(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_acceptance_rejects_empty_result_and_unknown_status(tmp_path: Path):
    from content_platform.overnight_acceptance import validate_overnight_result

    result = tmp_path / "result.json"
    result.write_text("", encoding="utf-8")
    report = validate_overnight_result(result, tmp_path / "state.json")
    assert report["passed"] is False
    assert "result_empty" in report["failures"]

    _write(result, {"status": "success"})
    report = validate_overnight_result(result, tmp_path / "state.json")
    assert report["passed"] is False
    assert "status_not_allowed" in report["failures"]


def test_acceptance_requires_real_artifacts_for_successful_video_task(tmp_path: Path):
    from content_platform.overnight_acceptance import validate_overnight_result

    result = tmp_path / "result.json"
    state = tmp_path / "state.json"
    _write(result, {"status": "partial", "tasks": [{"platform": "douyin_ai", "state": "handoff_ready"}]})
    _write(state, {"status": "partial", "tasks": [{"platform": "douyin_ai", "state": "handoff_ready", "job_id": "job-1", "artifacts": []}]})

    report = validate_overnight_result(result, state)
    assert report["passed"] is False
    assert "video_artifacts_missing:douyin_ai" in report["failures"]


def test_acceptance_accepts_evidenced_handoff_and_staged_tasks(tmp_path: Path):
    from content_platform.overnight_acceptance import validate_overnight_result

    result = tmp_path / "result.json"
    state = tmp_path / "state.json"
    _write(result, {"status": "partial"})
    _write(
        state,
        {
            "status": "partial",
            "tasks": [
                {"platform": "kuaishou", "state": "staged", "job_id": "job-1", "artifacts": [
                    {"kind": "video", "path": str(tmp_path / "final.mp4")},
                    {"kind": "cover", "path": str(tmp_path / "cover.png")},
                    {"kind": "publish_info", "path": str(tmp_path / "publish_info.json")},
                ]},
                {"platform": "tiktok", "state": "handoff_ready", "job_id": "job-2", "artifacts": [
                    {"kind": "video", "path": str(tmp_path / "final.mp4")},
                    {"kind": "cover", "path": str(tmp_path / "cover.png")},
                    {"kind": "publish_info", "path": str(tmp_path / "publish_info.json")},
                ]},
            ],
        },
    )
    for name in ("final.mp4", "cover.png", "publish_info.json"):
        (tmp_path / name).write_bytes(b"evidence")
    (tmp_path / "scene_manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tts_config.json").write_text("{}", encoding="utf-8")

    report = validate_overnight_result(result, state)
    assert report["passed"] is True
    assert report["failures"] == []
