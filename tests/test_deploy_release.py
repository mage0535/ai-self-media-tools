import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.deploy_release import deploy_release


def _git_source(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "run.py").write_text("print('release')\n", encoding="utf-8")
    (root / "README.md").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
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
    current = tmp_path / "current"
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
    assert result["release_root"] == str(release.resolve())
    assert (release / "release-metadata.json").is_file()
    assert attestation.is_file()
    assert json.loads((release / "release-metadata.json").read_text(encoding="utf-8"))["attestation_path"] == str(attestation.resolve())
    assert current.is_symlink()
    assert current.resolve() == release.resolve()
    assert not (release / "README.md").stat().st_mode & 0o222


def test_deploy_requires_successful_junit(tmp_path: Path, monkeypatch):
    source, config, report, rollback = _case(tmp_path)
    report.write_text("<testsuite tests='1' failures='1' errors='0'/>", encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(source))

    with pytest.raises(Exception, match="JUnit|failures"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=tmp_path / "current",
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=tmp_path / "data",
            release_name="failed",
        )
