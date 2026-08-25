from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest

from scripts.runtime_release_audit import ReleaseAuditError, audit_release, write_metadata


def _git_repo(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "baseline"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _valid_case(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _git_repo(source_root)
    release_root = tmp_path / "release"
    release_root.mkdir()
    for relative in ("README.md", "scripts/run.py"):
        destination = release_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)
    rollback_target = tmp_path / "rollback"
    (rollback_target / "scripts").mkdir(parents=True)
    (rollback_target / "scripts" / "run.py").write_text("print('rollback')\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    report_path = tmp_path / "junit.xml"
    config_path.write_text(json.dumps({"mode": "safe"}), encoding="utf-8")
    report_path.write_text("<testsuite tests='1' failures='0'/>", encoding="utf-8")
    return source_root, release_root, config_path, report_path, rollback_target


def test_rejects_mismatched_source_release_and_configured_script_roots(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    release_root = tmp_path / "releases" / "abc123"
    configured_script_root = tmp_path / "releases" / "other456" / "scripts"
    source_root.mkdir(parents=True)
    release_root.mkdir(parents=True)
    configured_script_root.mkdir(parents=True)
    config_path = tmp_path / "config.json"
    report_path = tmp_path / "junit.xml"
    rollback_target = tmp_path / "rollback"
    (rollback_target / "scripts").mkdir(parents=True)
    (rollback_target / "scripts" / "run.py").write_text("rollback\n", encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    report_path.write_text("<testsuite/>", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="source.*release.*script"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=configured_script_root,
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_dirty_source_root(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    _git_repo(source_root)
    release_root = tmp_path / "release"
    (release_root / "scripts").mkdir(parents=True)
    (source_root / "uncommitted.txt").write_text("not released", encoding="utf-8")
    config_path = tmp_path / "config.json"
    report_path = tmp_path / "junit.xml"
    rollback_target = tmp_path / "rollback"
    (rollback_target / "scripts").mkdir(parents=True)
    (rollback_target / "scripts" / "run.py").write_text("rollback\n", encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    report_path.write_text("<testsuite/>", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="dirty|uncommitted"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_writes_immutable_release_metadata_with_hashes_and_rollback_target(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    metadata = audit_release(
        source_root=source_root,
        release_root=release_root,
        configured_script_root=release_root / "scripts",
        config_path=config_path,
        test_report_path=report_path,
        rollback_target=rollback_target,
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
    assert saved["rollback_target"] == str(rollback_target.resolve())
    with pytest.raises(ReleaseAuditError, match="already exists"):
        write_metadata(metadata, destination)


def test_rejects_release_content_that_differs_from_source(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (release_root / "README.md").write_text("tampered\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="hash|content"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_release_missing_a_tracked_file(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (release_root / "README.md").unlink()
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="missing|release"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_environment_code_root_that_differs_from_release(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(tmp_path / "another-release"))

    with pytest.raises(ReleaseAuditError, match="environment|code root"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_missing_environment_code_root(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    monkeypatch.delenv("CONTENT_PLATFORM_CODE_ROOT", raising=False)

    with pytest.raises(ReleaseAuditError, match="CONTENT_PLATFORM_CODE_ROOT"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


@pytest.mark.parametrize("missing", ["config_path", "test_report_path", "rollback_target"])
def test_rejects_missing_required_release_evidence(tmp_path: Path, missing: str, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    values = {
        "config_path": config_path,
        "test_report_path": report_path,
        "rollback_target": rollback_target,
    }
    values[missing] = None
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="required|evidence"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            **values,
        )


@pytest.mark.parametrize("missing", ["config_path", "test_report_path"])
def test_rejects_required_evidence_path_that_does_not_exist(tmp_path: Path, missing: str, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    values = {
        "config_path": config_path,
        "test_report_path": report_path,
        "rollback_target": rollback_target,
    }
    values[missing] = tmp_path / "does-not-exist"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="required evidence"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            **values,
        )


def test_rejects_invalid_rollback_target(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, _ = _valid_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="rollback"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=release_root,
        )


def test_rejects_rollback_target_without_safe_entrypoint(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (rollback_target / "scripts" / "run.py").unlink()
    (rollback_target / "scripts" / "README.txt").write_text("not executable\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="entry|runnable|syntax"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_rollback_target_with_invalid_python_entrypoint(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (rollback_target / "scripts" / "run.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="syntax|compile|rollback"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_rollback_target_with_invalid_shell_entrypoint(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (rollback_target / "scripts" / "broken.sh").write_text("if then\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))
    monkeypatch.setenv("PATH", f"C:\\Program Files\\Git\\bin{os.pathsep}{os.environ['PATH']}")

    with pytest.raises(ReleaseAuditError, match="shell|syntax|rollback"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_metadata_path_outside_release(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))
    metadata = audit_release(
        source_root=source_root,
        release_root=release_root,
        configured_script_root=release_root / "scripts",
        config_path=config_path,
        test_report_path=report_path,
        rollback_target=rollback_target,
    )

    with pytest.raises(ReleaseAuditError, match="metadata.*release"):
        write_metadata(metadata, tmp_path / "outside.json")


def test_accepts_consistent_release_and_all_evidence(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))
    metadata = audit_release(
        source_root=source_root,
        release_root=release_root,
        configured_script_root=release_root / "scripts",
        config_path=config_path,
        test_report_path=report_path,
        rollback_target=rollback_target,
    )

    destination = release_root / "release-metadata.json"
    write_metadata(metadata, destination)
    saved = json.loads(destination.read_text(encoding="utf-8"))
    assert saved["release_root"] == str(release_root.resolve())
    assert saved["rollback_target"] == str(rollback_target.resolve())
