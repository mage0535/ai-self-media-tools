import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import deploy_release as deploy_release_module
from scripts.deploy_release import (
    _tracked_modes,
    attest_existing_release as attest_existing_release_module,
    deploy_release,
    deploy_release as _deploy_release,
    init_signing_key,
    rollback_release,
    prepare_bootstrap_release,
)
from scripts.runtime_release_audit import ReleaseAuditError, audit_release, verify_metadata, write_metadata


def _fixture_evidence_runner(argv, cwd, stdout_path):
    if argv[2] == "pytest":
        junit = Path(next(item.split("=", 1)[1] for item in argv if item.startswith("--junitxml=")))
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text("<testsuite tests='900' failures='0' errors='0'/>", encoding="utf-8")
    else:
        stdout_path.write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
    return type("Result", (), {"returncode": 0, "stdout": ""})()


def deploy_release(**kwargs):
    kwargs.setdefault("evidence_runner", _fixture_evidence_runner)
    return _deploy_release(**kwargs)


def _git_source(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    run = root / "scripts" / "run.py"
    run.write_text("print('release')\n", encoding="utf-8")
    run.chmod(0o755)
    (root / "systemd").mkdir()
    (root / "systemd" / "hermes-content-platform.service").write_text(
        "[Service]\n"
        "Environment=CONTENT_PLATFORM_HOME=%h/.ai-self-media-tools-current\n"
        "Environment=CONTENT_PLATFORM_CODE_ROOT=%h/.ai-self-media-tools-current\n"
        "Environment=PYTHONPATH=%h/.ai-self-media-tools-current\n"
        "Environment=CONTENT_PLATFORM_DATA_DIR=%h/.ai-self-media-tools/data\n"
        "Environment=CONTENT_PLATFORM_SECRETS_DIR=%h/.ai-self-media-tools/secrets\n"
        "Environment=CONTENT_PLATFORM_CONFIG=%h/.ai-self-media-tools/config.json\n"
        "Environment=CONTENT_PLATFORM_RUNTIME_MODE=production\n"
        "WorkingDirectory=%h/.ai-self-media-tools-current\n"
        "ExecStart=/bin/bash %h/.ai-self-media-tools-current/scripts/run.py\n",
        encoding="utf-8",
    )
    (root / "systemd" / "hermes-content-platform.timer").write_text(
        "[Timer]\nOnCalendar=*-*-* 00:00:00\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "update-index", "--chmod=+x", "scripts/run.py"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "release"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _case(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _git_source(source)
    config = tmp_path / "config.json"
    config.write_text('{"mode":"safe"}\n', encoding="utf-8")
    report = tmp_path / "junit.xml"
    report.write_text("<testsuite tests='900' failures='0' errors='0'/>", encoding="utf-8")
    (tmp_path / "project-audit.json").write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
    secrets = tmp_path / "secrets"
    init_signing_key(secrets)
    rollback = tmp_path / "rollback"
    (rollback / "scripts").mkdir(parents=True)
    (rollback / "README.md").write_text("release\n", encoding="utf-8")
    (rollback / "scripts" / "run.py").write_text("print('release')\n", encoding="utf-8")
    shutil.copytree(source / "systemd", rollback / "systemd")
    validation = tmp_path / "rollback-validation"
    (validation / "scripts").mkdir(parents=True)
    (validation / "scripts" / "run.py").write_text("print('validation')\n", encoding="utf-8")
    previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(rollback)
    try:
        rollback_metadata = audit_release(
            source_root=source,
            release_root=rollback,
            configured_script_root=rollback / "scripts",
            config_path=config,
            test_report_path=report,
            rollback_target=validation,
            attestation_path=tmp_path / "data" / "release-attestations" / "rollback.sha256",
            signing_key_path=secrets / "release-signing.key",
            trusted_secrets_root=secrets,
            project_audit_report_path=tmp_path / "project-audit.json",
        )
        write_metadata(rollback_metadata, rollback / "release-metadata.json", signing_key_path=secrets / "release-signing.key")
    finally:
        if previous_root is None:
            os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
        else:
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
    return source, config, report, rollback


def _existing_release_case(tmp_path: Path):
    source, config, report, rollback = _case(tmp_path)
    (tmp_path / "data" / "release-attestations" / "rollback.sha256").unlink()
    releases = tmp_path / "releases"
    release = releases / "legacy"
    for relative in ("README.md", "scripts/run.py"):
        destination = release / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    shutil.copytree(source / "systemd", release / "systemd")
    current = tmp_path / ".ai-self-media-tools-current"
    current.symlink_to(release, target_is_directory=True)
    return source, config, report, rollback, releases, release, current


def attest_existing_release(**kwargs):
    kwargs.setdefault("evidence_runner", _fixture_evidence_runner)
    return attest_existing_release_module(**kwargs)


def test_attest_existing_rejects_source_release_mismatch(tmp_path: Path):
    source, config, report, rollback, _, release, current = _existing_release_case(tmp_path)
    (source / "README.md").write_text("different\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "different"],
        cwd=source, check=True, capture_output=True,
    )

    with pytest.raises(ReleaseAuditError, match="hash|mismatch|tracked"):
        attest_existing_release(
            source_root=source, target_release=release, current_link=current,
            config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
        )


def test_prepare_bootstrap_builds_signed_release_without_switching_current(tmp_path, monkeypatch):
    source, config, report, _rollback = _case(tmp_path)
    releases = tmp_path / "releases"
    current = tmp_path / ".ai-self-media-tools-current"
    old = tmp_path / "old-current"
    old.mkdir()
    current.symlink_to(old, target_is_directory=True)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    result = prepare_bootstrap_release(
        source_root=source, releases_root=releases, current_link=current,
        config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
        release_name="bootstrap-clean", evidence_runner=_fixture_evidence_runner,
    )

    release = releases / "bootstrap-clean"
    assert result["prepared"] is True
    assert result["activated"] is False
    assert current.resolve() == old.resolve()
    assert json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))["bootstrap"] is True
    assert (tmp_path / "data" / "release-attestations" / "bootstrap-clean.sha256").is_file()


@pytest.mark.parametrize("operation", ["bootstrap", "deploy"])
def test_config_preflight_stops_before_evidence_and_preserves_environment(tmp_path, monkeypatch, operation):
    source, config, _, rollback = _case(tmp_path)
    config = tmp_path / "candidate-config.json"
    config.write_text(json.dumps({"tools": {"bridge": str(tmp_path / "external.py")}}), encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", "untouched-code")
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", "untouched-data")
    before = dict(os.environ)
    calls = []

    def evidence(*args, **kwargs):
        calls.append(args)
        return _fixture_evidence_runner(*args, **kwargs)

    kwargs = dict(source_root=source, releases_root=tmp_path / "releases", config_path=config,
                  data_root=tmp_path / "data", release_name="preflight", evidence_runner=evidence)
    function = prepare_bootstrap_release
    if operation == "deploy":
        function = deploy_release
        kwargs["rollback_target"] = rollback
    with pytest.raises(ReleaseAuditError, match="outside release"):
        function(**kwargs)
    assert calls == []
    assert not (tmp_path / "releases").exists()
    assert os.environ == before


@pytest.mark.parametrize("name", [".", "..", "../escape", "nested/name", "nested\\name", ""])
def test_bootstrap_invalid_name_has_no_side_effects(tmp_path, name):
    with pytest.raises(ReleaseAuditError, match="release_name"):
        prepare_bootstrap_release(
            source_root=tmp_path / "source", releases_root=tmp_path / "releases",
            config_path=tmp_path / "config.json", data_root=tmp_path / "data",
            release_name=name,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path_kind", ["traversal", "symlink"])
def test_bootstrap_validates_raw_source_before_resolving(tmp_path, path_kind):
    source, config, _, _ = _case(tmp_path)
    if path_kind == "traversal":
        supplied = source / ".." / "source"
    else:
        supplied = tmp_path / "source-alias"
        supplied.symlink_to(source, target_is_directory=True)
    with pytest.raises(ReleaseAuditError, match="source_root.*(forbidden|symlink)"):
        prepare_bootstrap_release(
            source_root=supplied, releases_root=tmp_path / "releases",
            config_path=config, data_root=tmp_path / "data", release_name="candidate",
            evidence_runner=_fixture_evidence_runner,
        )
    assert not (tmp_path / "releases").exists()


def test_bootstrap_missing_explicit_key_does_not_create_default(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git_source(source)
    with pytest.raises(ReleaseAuditError, match="signing key.*exist"):
        prepare_bootstrap_release(
            source_root=source, releases_root=tmp_path / "releases",
            config_path=tmp_path / "config.json", data_root=tmp_path / "data",
            signing_key=tmp_path / "secrets" / "custom.key", release_name="candidate",
        )
    assert not (tmp_path / "secrets").exists()
    assert not (tmp_path / "releases").exists()


def test_bootstrap_failed_evidence_preserves_foreign_target(tmp_path):
    source, config, _, _ = _case(tmp_path)
    target = tmp_path / "releases" / "candidate"

    def fail_with_foreign_target(*args, **kwargs):
        target.mkdir()
        (target / "sentinel").write_text("other builder", encoding="utf-8")
        raise RuntimeError("evidence failed")

    with pytest.raises(RuntimeError, match="evidence failed"):
        prepare_bootstrap_release(
            source_root=source, releases_root=target.parent, config_path=config,
            data_root=tmp_path / "data", release_name=target.name,
            evidence_runner=fail_with_foreign_target,
        )
    assert (target / "sentinel").read_text(encoding="utf-8") == "other builder"
    assert not list(tmp_path.glob("source-release-staging-*"))


def test_bootstrap_target_created_during_evidence_is_not_overwritten(tmp_path):
    source, config, _, _ = _case(tmp_path)
    target = tmp_path / "releases" / "candidate"

    def evidence_with_foreign_target(*args, **kwargs):
        target.mkdir(exist_ok=True)
        return _fixture_evidence_runner(*args, **kwargs)

    with pytest.raises((ReleaseAuditError, FileExistsError)):
        prepare_bootstrap_release(
            source_root=source, releases_root=target.parent, config_path=config,
            data_root=tmp_path / "data", release_name=target.name,
            evidence_runner=evidence_with_foreign_target,
        )
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_bootstrap_freeze_failure_removes_only_own_output(tmp_path, monkeypatch):
    source, config, _, _ = _case(tmp_path)
    target = tmp_path / "releases" / "candidate"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    def fail_freeze(_release):
        raise RuntimeError("freeze failed")

    monkeypatch.setattr(deploy_release_module, "_freeze_release", fail_freeze)
    with pytest.raises(RuntimeError, match="freeze failed"):
        prepare_bootstrap_release(
            source_root=source, releases_root=target.parent, config_path=config,
            data_root=tmp_path / "data", release_name=target.name,
            evidence_runner=_fixture_evidence_runner,
        )
    assert not target.exists()
    assert not (tmp_path / "data" / "release-attestations" / "candidate.sha256").exists()
    assert (tmp_path / "data" / "release-attestations" / "rollback.sha256").is_file()
    assert os.environ["CONTENT_PLATFORM_CODE_ROOT"] == str(source)


def test_bootstrap_metadata_failure_removes_own_attestation(tmp_path, monkeypatch):
    source, config, _, _ = _case(tmp_path)
    target = tmp_path / "releases" / "candidate"
    attestation = tmp_path / "data" / "release-attestations" / "candidate.sha256"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    real_write_metadata = deploy_release_module.write_metadata

    def fail_metadata(*args, **kwargs):
        real_write_metadata(*args, **kwargs)
        raise RuntimeError("metadata failed")

    monkeypatch.setattr(deploy_release_module, "write_metadata", fail_metadata)
    with pytest.raises(RuntimeError, match="metadata failed"):
        prepare_bootstrap_release(
            source_root=source, releases_root=target.parent, config_path=config,
            data_root=tmp_path / "data", release_name=target.name,
            evidence_runner=_fixture_evidence_runner,
        )
    assert not target.exists()
    assert not attestation.exists()
    assert (tmp_path / "data" / "release-attestations" / "rollback.sha256").is_file()


def test_attest_existing_rejects_non_current_release(tmp_path: Path):
    source, config, report, rollback, releases, release, current = _existing_release_case(tmp_path)
    other = releases / "other"
    shutil.copytree(release, other)

    with pytest.raises(ReleaseAuditError, match="current"):
        attest_existing_release(
            source_root=source, target_release=other, current_link=current,
            config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
        )


def test_attest_existing_rejects_existing_attestation(tmp_path: Path):
    source, config, report, rollback, _, release, current = _existing_release_case(tmp_path)
    attestation = tmp_path / "data" / "release-attestations" / "legacy.sha256"
    attestation.parent.mkdir(parents=True, exist_ok=True)
    attestation.write_text("already adopted\n", encoding="ascii")

    with pytest.raises(ReleaseAuditError, match="attestation|adopted|exists"):
        attest_existing_release(
            source_root=source, target_release=release, current_link=current,
            config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
        )


def test_attest_existing_creates_bootstrap_attestation_and_freezes_release(tmp_path: Path, monkeypatch):
    source, config, report, rollback, _, release, current = _existing_release_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release))

    result = attest_existing_release(
        source_root=source, target_release=release, current_link=current,
        config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
    )

    metadata = json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))
    assert result["operation"] == "attest-existing"
    assert metadata["bootstrap"] is True
    assert metadata["rollback_target"] == ""
    assert Path(result["attestation_path"]).is_file()
    assert current.resolve() == release.resolve()
    assert (release / "README.md").stat().st_mode & 0o222 == 0
    assert verify_metadata(
        release / "release-metadata.json",
        current_release_root=release,
        signing_key_path=tmp_path / "secrets" / "release-signing.key",
        trusted_secrets_root=tmp_path / "secrets",
    )["bootstrap"] is True


def test_deploy_can_use_bootstrap_release_as_signed_rollback(tmp_path: Path, monkeypatch):
    source, config, report, rollback, releases, release, current = _existing_release_case(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release))
    attest_existing_release(
        source_root=source, target_release=release, current_link=current,
        config_path=config, data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
    )

    (source / "README.md").write_text("release B\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "release-b"],
        cwd=source, check=True, capture_output=True,
    )
    deploy_release(
        source_root=source, releases_root=releases, current_link=current,
        config_path=config, rollback_target=release, data_root=tmp_path / "data",
        secrets_root=tmp_path / "secrets", release_name="release-b",
    )

    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(releases / "release-b"))
    rollback_release(target_release=release, current_link=current, data_root=tmp_path / "data")
    assert current.resolve() == release.resolve()


def test_deploy_builds_attested_readonly_release_and_switches_current(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    releases = tmp_path / "releases"
    data = tmp_path / "data"
    current = tmp_path / ".ai-self-media-tools-current"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    result = deploy_release(
        source_root=source,
        releases_root=releases,
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="abc123",
    )

    release = releases / "abc123"
    attestation = data / "release-attestations" / "abc123.sha256"
    signing_key = tmp_path / "secrets" / "release-signing.key"
    assert result["release_root"] == str(release.resolve())
    assert (release / "release-metadata.json").is_file()
    assert attestation.is_file()
    assert signing_key.is_file()
    assert signing_key.stat().st_size == 32
    if os.name != "nt":
        assert signing_key.stat().st_mode & 0o777 == 0o600
    assert set(json.loads(attestation.read_text(encoding="ascii"))) == {"release_digest", "hmac_sha256"}
    saved_metadata = json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))
    assert saved_metadata["attestation_path"] == str(attestation.resolve())
    assert saved_metadata["signing_key_id"]
    assert saved_metadata["signing_key_hash"]
    assert saved_metadata["junit_tests"] == 900
    assert saved_metadata["project_audit_report_hash"]
    assert "signing_key_path" not in saved_metadata
    assert saved_metadata["rollback_rehearsal"]["target_release"] == str((tmp_path / "rollback").resolve())
    assert saved_metadata["rollback_rehearsal"]["passed"] is True
    assert current.is_symlink()
    assert current.resolve() == release.resolve()
    assert _tracked_modes(source)["scripts/run.py"] == "100755"
    if os.name != "nt":
        assert (release / "scripts" / "run.py").stat().st_mode & 0o777 == 0o555
    assert (release / "README.md").stat().st_mode & 0o777 == 0o444


def test_deploy_runs_source_evidence_commands_and_binds_manifest(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    calls = []

    def runner(argv, cwd, stdout_path):
        calls.append((list(argv), Path(cwd), Path(stdout_path)))
        if argv[2] == "pytest":
            junit = Path(next(item.split("=", 1)[1] for item in argv if item.startswith("--junitxml=")))
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.write_text("<testsuite tests='900' failures='0' errors='0'/>", encoding="utf-8")
        else:
            stdout_path.write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    result = _deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=tmp_path / "data",
        secrets_root=tmp_path / "secrets",
        evidence_runner=runner,
        release_name="evidence",
    )

    assert [call[0][1:3] for call in calls] == [["-m", "pytest"], ["-m", "content_platform"]]
    manifest = tmp_path / "data" / "release-evidence" / "evidence" / "evidence_manifest.json"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["commit"]
    assert all(item["returncode"] == 0 and item["sha256"] for item in saved["evidence"])
    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["evidence_manifest_hash"]


def test_deploy_freezes_commit_a_across_source_b_and_post_audit_source_change(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    commit_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    calls = []

    def runner(argv, cwd, stdout_path):
        calls.append(Path(cwd))
        if argv[2] == "pytest":
            (source / "README.md").write_text("release B\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "release-b"],
                cwd=source, check=True, capture_output=True,
            )
            junit = Path(next(item.split("=", 1)[1] for item in argv if item.startswith("--junitxml=")))
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.write_text("<testsuite tests='900' failures='0' errors='0'/>", encoding="utf-8")
        else:
            stdout_path.write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    original_audit = deploy_release_module.audit_release

    def audit_then_change_source(**kwargs):
        metadata = original_audit(**kwargs)
        (source / "README.md").write_text("post-audit source change\n", encoding="utf-8")
        return metadata

    monkeypatch.setattr(deploy_release_module, "audit_release", audit_then_change_source)
    result = _deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=config,
        rollback_target=rollback,
        data_root=tmp_path / "data",
        secrets_root=tmp_path / "secrets",
        evidence_runner=runner,
        release_name="race-safe",
    )

    release = Path(result["release_root"])
    manifest = json.loads((tmp_path / "data" / "release-evidence" / "race-safe" / "evidence_manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))
    assert len(set(calls)) == 1
    assert calls[0] != source
    assert manifest["commit"] == commit_a
    assert metadata["commit"] == commit_a
    assert (release / "README.md").read_text(encoding="utf-8") == "release\n"


def test_deploy_rejects_dirty_staging_worktree_and_cleans_it(tmp_path: Path):
    source, config, report, rollback = _case(tmp_path)

    def runner(argv, cwd, stdout_path):
        (Path(cwd) / "staging-dirty.txt").write_text("dirty\n", encoding="utf-8")
        if argv[2] == "pytest":
            junit = Path(next(item.split("=", 1)[1] for item in argv if item.startswith("--junitxml=")))
            junit.parent.mkdir(parents=True, exist_ok=True)
            junit.write_text("<testsuite tests='900' failures='0' errors='0'/>", encoding="utf-8")
        else:
            stdout_path.write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with pytest.raises(ReleaseAuditError, match="dirty|uncommitted"):
        _deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            secrets_root=tmp_path / "secrets",
            evidence_runner=runner,
            release_name="dirty-staging",
        )

    assert not list(source.parent.glob(f"{source.name}-release-staging-*"))


def test_deploy_requires_successful_junit(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    report.write_text("<testsuite tests='1' failures='1' errors='0'/>", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(Exception, match="JUnit|failures"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            release_name="failed",
        )


def test_init_signing_key_is_explicit_and_does_not_rotate(tmp_path: Path):
    secrets = tmp_path / "secrets"
    key = init_signing_key(secrets)
    original = key.read_bytes()
    assert len(original) == 32
    with pytest.raises(ReleaseAuditError, match="exists|rotate|overwrite"):
        init_signing_key(secrets)
    assert key.read_bytes() == original


def test_deploy_rejects_missing_signing_key(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    (tmp_path / "secrets" / "release-signing.key").unlink()
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(ReleaseAuditError, match="key|signing|exist"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            secrets_root=tmp_path / "secrets",
            release_name="missing-key",
        )


def test_deploy_rejects_arbitrary_secrets_directory(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    arbitrary = tmp_path / "arbitrary-secrets"
    (arbitrary / "release-signing.key").parent.mkdir(parents=True)
    (arbitrary / "release-signing.key").write_bytes(b"k" * 32)
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(ReleaseAuditError, match="stable|secrets|boundary"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            secrets_root=arbitrary,
            release_name="bad-secrets",
        )


def test_deploy_rejects_failed_project_audit_report(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    audit_report = tmp_path / "project-audit.json"
    audit_report.write_text(json.dumps({"ok": False, "issues": ["bad"]}), encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(ReleaseAuditError, match="project audit|issues|audit"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            project_audit_report=audit_report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            secrets_root=tmp_path / "secrets",
            release_name="bad-audit",
        )


def test_deploy_rejects_junit_below_production_threshold(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    report.write_text("<testsuite tests='899' failures='0' errors='0'/>", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(ReleaseAuditError, match="tests|900|JUnit"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            secrets_root=tmp_path / "secrets",
            release_name="few-tests",
        )


def test_verify_requires_hmac_key_and_rejects_plaintext_or_tampered_signature(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    data = tmp_path / "data"
    current = tmp_path / ".ai-self-media-tools-current"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    deployed = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="signed",
    )
    release = Path(deployed["release_root"])
    metadata = release / "release-metadata.json"
    attestation = data / "release-attestations" / "signed.sha256"
    key = tmp_path / "secrets" / "release-signing.key"
    original_key = key.read_bytes()
    original_attestation = json.loads(attestation.read_text(encoding="ascii"))
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release))

    key.unlink()
    with pytest.raises(ReleaseAuditError, match="key|signing|attestation"):
        verify_metadata(metadata, current_release_root=release)

    key.write_bytes(original_key)
    attestation.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="HMAC|signature|attestation|JSON"):
        verify_metadata(metadata, current_release_root=release)

    payload = original_attestation
    payload["hmac_sha256"] = "0" * 64
    attestation.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="HMAC|signature|attestation"):
        verify_metadata(metadata, current_release_root=release)


def test_data_attestation_replacement_without_stable_secrets_key_fails(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    data = tmp_path / "data"
    secrets = tmp_path / "secrets"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    deployed = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        secrets_root=secrets,
        release_name="stable-key",
    )
    release = Path(deployed["release_root"])
    attestation = data / "release-attestations" / "stable-key.sha256"
    (secrets / "release-signing.key").unlink()
    attestation.write_text('{"release_digest":"' + "0" * 64 + '","hmac_sha256":"' + "0" * 64 + '"}\n', encoding="ascii")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release))

    with pytest.raises(ReleaseAuditError, match="key|signing|attestation"):
        verify_metadata(release / "release-metadata.json", current_release_root=release, signing_key_path=secrets / "release-signing.key")


@pytest.mark.parametrize("location", ["data", "release"])
def test_deploy_rejects_signing_key_outside_stable_secrets_boundary(tmp_path: Path, monkeypatch, location: str):
    source, config, report, rollback = _case(tmp_path)
    data = tmp_path / "data"
    releases = tmp_path / "releases"
    key = data / "release-signing.key" if location == "data" else releases / "release-signing.key"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(ReleaseAuditError, match="signing|secret|boundary|data|release"):
        deploy_release(
            source_root=source,
            releases_root=releases,
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=data,
            signing_key=key,
            release_name="bad-key",
        )


def test_deploy_rewrites_old_internal_config_paths_and_rejects_external_script(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    deploy_config = tmp_path / "deploy-config.json"
    old_release = tmp_path / ".ai-self-media-tools-releases" / "old"
    old_script = old_release / "scripts" / "run.py"
    deploy_config.write_text(
        json.dumps({"data_dir": str(old_release / "data"), "media": {"script": str(old_script)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    result = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=deploy_config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=tmp_path / "data",
        release_name="rewritten",
    )
    assert result["ok"] is True

    deploy_config.write_text(
        json.dumps({"media": {"script": str(tmp_path / "legacy-release" / "scripts" / "run.py")}}),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseAuditError, match="config|script|release|path"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases-2",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=deploy_config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data-2",
            release_name="rejected",
        )


def _external_bridge_config(tmp_path: Path, *, digest: str | None = None, config_key: str = "tools.agent_reach.bridge"):
    hermes = tmp_path / ".hermes"
    bridge = hermes / "scripts" / "reach_bridge.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("print('bridge')\n", encoding="utf-8")
    actual = hashlib.sha256(bridge.read_bytes()).hexdigest()
    config = tmp_path / "external-config.json"
    config.write_text(json.dumps({
        "data_dir": str(tmp_path / "data"),
        "tools": {"agent_reach": {"bridge": str(bridge)}},
        "external_runtime_dependencies": {
            "schema": "external_runtime_dependencies_v1",
            "items": [{
                "id": "agent_reach_bridge", "kind": "hermes_bridge",
                "config_key": config_key, "path": str(bridge), "sha256": digest or actual,
            }],
        },
    }), encoding="utf-8")
    return hermes, bridge, config


def test_config_preflight_accepts_hash_bound_hermes_bridge(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _git_source(source)
    hermes, _, config = _external_bridge_config(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    deploy_release_module.preflight_runtime_config(config, source, tmp_path / "data", tmp_path / "secrets")


@pytest.mark.parametrize("fault", ["hash", "config_key", "symlink"])
def test_config_preflight_rejects_untrusted_hermes_bridge(tmp_path, monkeypatch, fault):
    source = tmp_path / "source"
    source.mkdir()
    _git_source(source)
    hermes, bridge, config = _external_bridge_config(
        tmp_path, digest="0" * 64 if fault == "hash" else None,
        config_key="tools.other.bridge" if fault == "config_key" else "tools.agent_reach.bridge",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    if fault == "symlink":
        target = bridge.with_name("actual.py")
        bridge.rename(target)
        bridge.symlink_to(target)
    with pytest.raises(ReleaseAuditError, match="external|bridge|hash|config_key|symlink"):
        deploy_release_module.preflight_runtime_config(config, source, tmp_path / "data", tmp_path / "secrets")


def test_rollback_verifies_target_and_atomically_switches_current(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    releases = tmp_path / "releases"
    data = tmp_path / "data"
    current = tmp_path / ".ai-self-media-tools-current"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    deployed = deploy_release(
        source_root=source,
        releases_root=releases,
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="good",
    )

    result = rollback_release(
        target_release=deployed["release_root"],
        current_link=current,
        data_root=data,
    )

    assert result["release_root"] == deployed["release_root"]
    assert current.resolve() == Path(deployed["release_root"]).resolve()


def test_static_systemd_service_is_not_restored_with_enable():
    from scripts.deploy_release import query_systemd_unit_states, _restore_systemd_states

    calls = []
    class Result:
        def __init__(self, returncode=0, stdout=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, ""

    def inspect(argv, **_kwargs):
        if "is-enabled" in argv:
            return Result(0, "static\n")
        if "is-active" in argv:
            return Result(0, "active\n")
        calls.append(argv)
        return Result()

    states = query_systemd_unit_states(["worker.service"], runner=inspect)
    assert states["worker.service"]["enabled"] is False
    assert states["worker.service"]["active"] is True
    _restore_systemd_states(states, runner=inspect)
    assert not any(call[-2:] == ["enable", "worker.service"] for call in calls)
    assert any(call[-2:] == ["start", "worker.service"] for call in calls)


def test_rollback_rejects_target_without_audited_metadata(tmp_path: Path):
    target = tmp_path / "unaudited"
    target.mkdir()
    with pytest.raises(Exception, match="metadata|attestation|audit|exist|signing|secret"):
        rollback_release(
            target_release=target,
            current_link=tmp_path / ".ai-self-media-tools-current",
            data_root=tmp_path / "data",
        )


def test_rollback_cli_verifies_and_switches_audited_target(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    releases = tmp_path / "releases"
    data = tmp_path / "data"
    current = tmp_path / ".ai-self-media-tools-current"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    deployed = deploy_release(
        source_root=source,
        releases_root=releases,
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="cli-good",
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_systemctl = tmp_path / "fake-systemctl.py"
    fake_systemctl.write_text(
        "import sys\n"
        "op = sys.argv[2]\n"
        "if op == 'is-enabled': sys.exit(1)\n"
        "if op == 'is-active': sys.exit(3)\n"
        "if op == 'show':\n"
        " print('ExecStart=/bin/bash %h/.ai-self-media-tools-current/scripts/run.py')\n"
        " print('WorkingDirectory=%h/.ai-self-media-tools-current')\n"
        " print('Environment=CONTENT_PLATFORM_HOME=%h/.ai-self-media-tools-current')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    (fake_bin / "systemctl.cmd").write_text(
        f'@"{sys.executable}" "{fake_systemctl}" %*\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/deploy_release.py",
            "rollback",
            "--target-release",
            deployed["release_root"],
            "--current-link",
            str(current),
            "--data-root",
            str(data),
            "--secrets-root",
            str(tmp_path / "secrets"),
            "--systemd-unit-dir",
            "",
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "CONTENT_PLATFORM_CODE_ROOT": str(source), "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert current.resolve() == Path(deployed["release_root"]).resolve()


def test_rollback_a_survives_source_b_and_rejects_all_a_tampering(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    releases = tmp_path / "releases"
    data = tmp_path / "data"
    current = tmp_path / ".ai-self-media-tools-current"
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    deployed_a = deploy_release(
        source_root=source,
        releases_root=releases,
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="release-a",
    )
    release_a = Path(deployed_a["release_root"])
    metadata_a = release_a / "release-metadata.json"
    attestation_a = data / "release-attestations" / "release-a.sha256"
    original_metadata = metadata_a.read_bytes()
    original_readme = (release_a / "README.md").read_bytes()

    (source / "README.md").write_text("release B\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "release-b"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    deploy_release(
        source_root=source,
        releases_root=releases,
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="release-b",
    )

    source.rename(tmp_path / "source-no-longer-available")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release_a))
    assert verify_metadata(metadata_a, current_release_root=release_a)["commit"]
    assert rollback_release(target_release=release_a, current_link=current, data_root=data)["ok"] is True

    release_a.chmod(0o755)
    (release_a / "README.md").chmod(0o644)
    (release_a / "README.md").write_text("release A tampered\n", encoding="utf-8")
    with pytest.raises(ReleaseAuditError, match="attestation|hash|release|evidence"):
        verify_metadata(metadata_a, current_release_root=release_a)
    (release_a / "README.md").write_bytes(original_readme)

    tampered_metadata = json.loads(original_metadata.decode("utf-8"))
    tampered_metadata["commit"] = "0" * 40
    metadata_a.chmod(0o644)
    metadata_a.write_text(json.dumps(tampered_metadata), encoding="utf-8")
    with pytest.raises(ReleaseAuditError, match="attestation|hash|release|evidence"):
        verify_metadata(metadata_a, current_release_root=release_a)
    metadata_a.write_bytes(original_metadata)

    attestation_a.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="attestation|hash|mismatch"):
        verify_metadata(metadata_a, current_release_root=release_a)
