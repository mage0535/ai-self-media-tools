import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.deploy_release import _tracked_modes, deploy_release, rollback_release
from scripts.runtime_release_audit import ReleaseAuditError, verify_metadata


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
    report.write_text("<testsuite tests='1' failures='0' errors='0'/>", encoding="utf-8")
    rollback = tmp_path / "rollback"
    (rollback / "scripts").mkdir(parents=True)
    (rollback / "scripts" / "run.py").write_text("print('rollback')\n", encoding="utf-8")
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
    signing_key = data / "release-signing.key"
    assert result["release_root"] == str(release.resolve())
    assert (release / "release-metadata.json").is_file()
    assert attestation.is_file()
    assert signing_key.is_file()
    assert signing_key.stat().st_size == 32
    if os.name != "nt":
        assert signing_key.stat().st_mode & 0o777 == 0o600
    assert set(json.loads(attestation.read_text(encoding="ascii"))) == {"release_digest", "hmac_sha256"}
    assert json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))["attestation_path"] == str(attestation.resolve())
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
    key = data / "release-signing.key"
    original_attestation = json.loads(attestation.read_text(encoding="ascii"))
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(release))

    key.unlink()
    with pytest.raises(ReleaseAuditError, match="key|signing|attestation"):
        verify_metadata(metadata, current_release_root=release)

    key.write_bytes(b"k" * 32)
    attestation.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="HMAC|signature|attestation|JSON"):
        verify_metadata(metadata, current_release_root=release)

    payload = original_attestation
    payload["hmac_sha256"] = "0" * 64
    attestation.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(ReleaseAuditError, match="HMAC|signature|attestation"):
        verify_metadata(metadata, current_release_root=release)


def test_deploy_rewrites_old_internal_config_paths_and_rejects_external_script(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    old_release = tmp_path / ".ai-self-media-tools-releases" / "old"
    old_script = old_release / "scripts" / "run.py"
    config.write_text(
        json.dumps({"data_dir": str(old_release / "data"), "media": {"script": str(old_script)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))
    result = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=tmp_path / "data",
        release_name="rewritten",
    )
    assert result["ok"] is True

    config.write_text(
        json.dumps({"media": {"script": str(tmp_path / "legacy-release" / "scripts" / "run.py")}}),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseAuditError, match="config|script|release|path"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases-2",
            current_link=tmp_path / ".ai-self-media-tools-current",
            config_path=config,
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
    with pytest.raises(Exception, match="metadata|attestation|audit|exist"):
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
