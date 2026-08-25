import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.deploy_release import _tracked_modes, deploy_release, init_signing_key, rollback_release
from scripts.runtime_release_audit import ReleaseAuditError, audit_release, verify_metadata, write_metadata


def _git_source(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    run = root / "scripts" / "run.py"
    run.write_text("print('release')\n", encoding="utf-8")
    run.chmod(0o755)
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
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "CONTENT_PLATFORM_CODE_ROOT": str(source)},
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
    with pytest.raises(ReleaseAuditError, match="attestation|hash|release"):
        verify_metadata(metadata_a, current_release_root=release_a)
    (release_a / "README.md").write_bytes(original_readme)

    tampered_metadata = json.loads(original_metadata.decode("utf-8"))
    tampered_metadata["commit"] = "0" * 40
    metadata_a.chmod(0o644)
    metadata_a.write_text(json.dumps(tampered_metadata), encoding="utf-8")
    with pytest.raises(ReleaseAuditError, match="attestation|hash|release"):
        verify_metadata(metadata_a, current_release_root=release_a)
    metadata_a.write_bytes(original_metadata)

    attestation_a.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="attestation|hash|mismatch"):
        verify_metadata(metadata_a, current_release_root=release_a)
