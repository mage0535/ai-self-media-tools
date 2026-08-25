from pathlib import Path

import pytest

from scripts.runtime_release_audit import ReleaseAuditError, audit_release, write_metadata


def _git_repo(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("baseline\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "baseline"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_rejects_mismatched_source_release_and_configured_script_roots(tmp_path: Path):
    source_root = tmp_path / "source"
    release_root = tmp_path / "releases" / "abc123"
    configured_script_root = tmp_path / "releases" / "other456" / "scripts"
    source_root.mkdir(parents=True)
    release_root.mkdir(parents=True)
    configured_script_root.mkdir(parents=True)

    with pytest.raises(ReleaseAuditError, match="source.*release.*script"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=configured_script_root,
        )


def test_rejects_dirty_source_root(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _git_repo(source_root)
    release_root = tmp_path / "release"
    (release_root / "scripts").mkdir(parents=True)
    (source_root / "uncommitted.txt").write_text("not released", encoding="utf-8")

    with pytest.raises(ReleaseAuditError, match="dirty|uncommitted"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
        )


def test_writes_immutable_release_metadata_with_hashes_and_rollback_target(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _git_repo(source_root)
    release_root = tmp_path / "release"
    (release_root / "scripts").mkdir(parents=True)
    config_path = tmp_path / "config.json"
    report_path = tmp_path / "junit.xml"
    config_path.write_text('{"mode":"safe"}\n', encoding="utf-8")
    report_path.write_text("<testsuite tests='1' failures='0'/>", encoding="utf-8")

    metadata = audit_release(
        source_root=source_root,
        release_root=release_root,
        configured_script_root=release_root / "scripts",
        config_path=config_path,
        test_report_path=report_path,
        rollback_target="previous-release",
    )
    destination = tmp_path / "release" / "release-metadata.json"
    write_metadata(metadata, destination)

    import json

    saved = json.loads(destination.read_text(encoding="utf-8"))
    assert saved["commit"]
    assert saved["source_hashes"]["scripts/run.py"]
    assert saved["config_hash"]
    assert saved["test_report"] == str(report_path.resolve())
    assert saved["test_report_hash"]
    assert saved["rollback_target"] == "previous-release"
    with pytest.raises(ReleaseAuditError, match="already exists"):
        write_metadata(metadata, destination)
