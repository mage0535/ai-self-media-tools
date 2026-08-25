from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest

from scripts.runtime_release_audit import ReleaseAuditError, audit_release, verify_metadata, write_metadata


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


def test_rejects_release_file_not_in_source_tracked_files(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    injected = release_root / "content_platform" / "injected.py"
    injected.parent.mkdir(parents=True)
    injected.write_text("injected = True\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="not tracked|unexpected|release file"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_release_python_cache_and_bytecode_files(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    cache = release_root / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "run.cpython-314.pyc").write_bytes(b"cache")
    (release_root / "injected.pyc").write_bytes(b"bytecode")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="not tracked|unexpected|bytecode|cache"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_allows_release_metadata_file(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (release_root / "release-metadata.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    metadata = audit_release(
        source_root=source_root,
        release_root=release_root,
        configured_script_root=release_root / "scripts",
        config_path=config_path,
        test_report_path=report_path,
        rollback_target=rollback_target,
    )

    assert metadata["release_root"] == str(release_root.resolve())


def test_rejects_release_symlink_escape(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    link = release_root / "scripts" / "escape.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="symlink|release root|outside"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_symlink_release_root(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    real_release = tmp_path / "real-release"
    release_root.rename(real_release)
    try:
        release_root.symlink_to(real_release, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="release_root|symlink"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_parent_directory_symlink_in_config_path(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    outside = tmp_path / "outside-config"
    outside.mkdir()
    linked_parent = tmp_path / "linked-config"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    linked_config = linked_parent / config_path.name
    shutil.copy2(config_path, outside / config_path.name)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="symlink|path boundary"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=linked_config,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_rejects_symlink_child_parent_traversal_path(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    outside = tmp_path / "outside-config"
    outside.mkdir()
    linked_parent = tmp_path / "linked-config"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    shutil.copy2(config_path, outside / config_path.name)
    traversing_config = linked_parent / "child" / ".." / config_path.name
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match=r"\.\.|symlink|path boundary"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=traversing_config,
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


def test_rejects_shell_entrypoint_when_bash_validator_unavailable(tmp_path: Path, monkeypatch):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    (rollback_target / "scripts" / "run.sh").write_text("echo ok\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))
    monkeypatch.setenv("CONTENT_PLATFORM_BASH", str(tmp_path / "missing-bash"))

    with pytest.raises(ReleaseAuditError, match="validator_unavailable"):
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


@pytest.mark.parametrize("link_part", ["parent", "leaf"])
def test_rejects_code_root_environment_symlink_components(tmp_path: Path, monkeypatch, link_part: str):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    outside = tmp_path / "real-code-root"
    shutil.copytree(release_root, outside)
    if link_part == "parent":
        parent = tmp_path / "linked-parent"
        try:
            parent.symlink_to(tmp_path, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        code_root = parent / release_root.name
    else:
        code_root = tmp_path / "linked-code-root"
        try:
            code_root.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(code_root))

    with pytest.raises(ReleaseAuditError, match="CONTENT_PLATFORM_CODE_ROOT|symlink|path boundary"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


@pytest.mark.parametrize("kind", ["root", "scripts", "entry"])
def test_rejects_symlinked_rollback_components(tmp_path: Path, monkeypatch, kind: str):
    source_root, release_root, config_path, report_path, rollback_target = _valid_case(tmp_path)
    outside = tmp_path / "outside-rollback"
    (outside / "scripts").mkdir(parents=True)
    (outside / "scripts" / "run.py").write_text("print('outside')\n", encoding="utf-8")
    if kind == "root":
        real = rollback_target
        rollback_target = tmp_path / "linked-rollback"
        try:
            rollback_target.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
    elif kind == "scripts":
        scripts = rollback_target / "scripts"
        scripts.rename(rollback_target / "real-scripts")
        try:
            scripts.symlink_to(rollback_target / "real-scripts", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
    else:
        entry = rollback_target / "scripts" / "run.py"
        entry.unlink()
        try:
            entry.symlink_to(outside / "scripts" / "run.py")
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_root))

    with pytest.raises(ReleaseAuditError, match="rollback|symlink|outside|contain"):
        audit_release(
            source_root=source_root,
            release_root=release_root,
            configured_script_root=release_root / "scripts",
            config_path=config_path,
            test_report_path=report_path,
            rollback_target=rollback_target,
        )


def test_verify_metadata_rejects_missing_metadata_and_tampered_evidence(tmp_path: Path, monkeypatch):
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

    assert verify_metadata(destination)["release_root"] == str(release_root.resolve())
    destination.write_text(destination.read_text(encoding="utf-8").replace(metadata["config_hash"], "0" * 64), encoding="utf-8")
    with pytest.raises(ReleaseAuditError, match="metadata|hash|config"):
        verify_metadata(destination)

    destination.unlink()
    with pytest.raises(ReleaseAuditError, match="metadata|exist"):
        verify_metadata(destination)


def test_verify_metadata_rejects_release_or_config_drift(tmp_path: Path, monkeypatch):
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

    (release_root / "README.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ReleaseAuditError, match="hash|release"):
        verify_metadata(destination)


@pytest.mark.parametrize("evidence", ["config", "report"])
def test_verify_metadata_rejects_current_config_or_junit_drift(tmp_path: Path, monkeypatch, evidence: str):
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
    path = config_path if evidence == "config" else report_path
    path.write_text(path.read_text(encoding="utf-8") + " drift", encoding="utf-8")

    with pytest.raises(ReleaseAuditError, match="hash|config|JUnit"):
        verify_metadata(destination)


def test_verify_metadata_successfully_checks_current_release_and_rollback(tmp_path: Path, monkeypatch):
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

    verified = verify_metadata(destination, current_release_root=release_root)
    assert verified["rollback_target"] == str(rollback_target.resolve())


def test_verify_metadata_cli_mode_returns_success(tmp_path: Path, monkeypatch):
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

    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python"),
            "scripts/runtime_release_audit.py",
            "verify_metadata",
            "--metadata-path",
            str(destination),
            "--release-root",
            str(release_root),
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "CONTENT_PLATFORM_CODE_ROOT": str(release_root)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["release_root"] == str(release_root.resolve())
