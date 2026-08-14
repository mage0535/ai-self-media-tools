from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_runtime_cleanup_archives_only_rebuildable_old_files(tmp_path: Path):
    from content_platform.runtime_hygiene import cleanup_runtime
    import os

    root = tmp_path / "data"
    old = root / "artifacts" / "job-old" / "intermediate.png"
    final = root / "artifacts" / "job-old" / "final.mp4"
    report = root / "artifacts" / "job-old" / "acceptance_summary.json"
    recent = root / "artifacts" / "job-recent" / "intermediate.png"
    for path in (old, final, report, recent):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"evidence")
    old_time = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    for path in (old, final, report):
        os.utime(path, (old_time, old_time))

    result = cleanup_runtime(root, retention_days=14, dry_run=False, disk_usage_percent=90)

    assert str(old) in result["archived"]
    assert not old.exists()
    assert final.exists()
    assert report.exists()
    assert recent.exists()
    archive = Path(result["archive"])
    assert archive.is_dir()
    assert (archive / "artifacts" / "job-old" / "intermediate.png").is_file()


def test_runtime_cleanup_refuses_to_run_when_disk_is_not_over_threshold(tmp_path: Path):
    from content_platform.runtime_hygiene import cleanup_runtime

    result = cleanup_runtime(tmp_path, retention_days=14, disk_usage_percent=70)

    assert result["archived"] == []
    assert result["reason"] == "disk_below_cleanup_threshold"
