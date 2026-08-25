"""Build, attest, freeze, and atomically activate a versioned runtime release."""

import argparse
import contextlib
import datetime as dt
import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_release_audit import (
    ReleaseAuditError,
    _create_signing_key,
    _git,
    _release_digest,
    _sha256,
    _assert_project_audit,
    _validate_raw_path,
    audit_release,
    verify_metadata,
    write_metadata,
)
from content_platform.cli import load_config

CURRENT_LINK_NAME = ".ai-self-media-tools-current"


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _tracked_paths(source_root: Path) -> list[Path]:
    output = _git(source_root, "ls-files", "-z")
    return [Path(item) for item in output.split("\0") if item]


def _tracked_modes(source_root: Path) -> dict[str, str]:
    output = _git(source_root, "ls-files", "--stage", "-z")
    modes = {}
    for record in output.split("\0"):
        if not record:
            continue
        header, relative = record.split("\t", 1)
        modes[relative] = header.split()[0]
    return modes


def _freeze_release(release_root: Path) -> None:
    for path in sorted(release_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o555)
        elif path.is_file():
            mode = path.stat().st_mode & 0o777
            path.chmod(0o555 if mode & 0o111 else 0o444)
    release_root.chmod(0o555)


def _current_path(current_link: Path | str | None) -> Path:
    current = Path(current_link).expanduser() if current_link is not None else Path.home() / CURRENT_LINK_NAME
    if current.name != CURRENT_LINK_NAME:
        raise ReleaseAuditError(f"current_link must use the systemd runtime root name: {CURRENT_LINK_NAME}")
    return current


def _activate(current_link: Path, release_root: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    temporary = current_link.parent / f".{current_link.name}.{uuid.uuid4().hex}.tmp"
    try:
        os.symlink(str(release_root), str(temporary), target_is_directory=True)
        try:
            os.replace(temporary, current_link)
        except PermissionError:
            if os.name != "nt" or not current_link.is_symlink():
                raise
            # Windows cannot atomically replace an existing directory symlink.
            current_link.unlink()
            os.replace(temporary, current_link)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()


def _validate_runtime_config(config_path: Path, release_root: Path, data_root: Path, secrets_root: Path) -> None:
    if not config_path.is_file():
        raise ReleaseAuditError(f"runtime config does not exist: {config_path}")
    loaded = load_config(str(config_path), str(data_root / "state.db"))
    if Path(loaded.get("data_dir", "")).expanduser().resolve() != data_root.resolve():
        raise ReleaseAuditError("runtime config data_dir is not the stable data root")

    def visit(value, key: str = ""):
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and value.lower().endswith((".py", ".sh")):
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = release_root / candidate
            resolved = candidate.resolve()
            try:
                resolved.relative_to(release_root.resolve())
            except ValueError as exc:
                raise ReleaseAuditError(f"configured {key} script is outside release: {value}") from exc
            if not resolved.is_file():
                raise ReleaseAuditError(f"configured {key} script does not exist in release: {value}")

    visit(loaded)


def _validate_signing_key_boundary(
    signing_key: Path,
    secrets_root: Path,
    data_root: Path,
    releases_root: Path,
    current_link: Path,
    release_root: Path | None = None,
) -> None:
    key = signing_key.resolve()
    secrets = secrets_root.resolve()
    if secrets != data_root.resolve().parent / "secrets" or key.parent != secrets:
        raise ReleaseAuditError("signing key must be directly under the stable secrets boundary")
    for label, boundary in (("data root", data_root), ("releases root", releases_root), ("current root", current_link)):
        try:
            key.relative_to(boundary.resolve())
        except ValueError:
            continue
        raise ReleaseAuditError(f"signing key must not be inside {label}")
    if release_root is not None:
        try:
            key.relative_to(release_root.resolve())
        except ValueError:
            return
        raise ReleaseAuditError("signing key must not be inside release")


def init_signing_key(secrets_root: Path | str) -> Path:
    secrets = Path(secrets_root).expanduser().resolve()
    _validate_raw_path(secrets, "secrets_root")
    if secrets.name != "secrets":
        raise ReleaseAuditError("secrets_root must be the stable secrets directory")
    return _create_signing_key(secrets / "release-signing.key")


def _signed_rollback_dry_run(target: Path, key: Path, secrets: Path) -> dict:
    previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
    previous_secrets = os.environ.get("CONTENT_PLATFORM_SECRETS_DIR")
    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
    os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = str(secrets)
    try:
        verify_metadata(
            target / "release-metadata.json",
            current_release_root=target,
            signing_key_path=key,
            trusted_secrets_root=secrets,
        )
        return {"target_release": str(target), "release_digest": _release_digest(target), "passed": True}
    finally:
        if previous_root is None:
            os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
        else:
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
        if previous_secrets is None:
            os.environ.pop("CONTENT_PLATFORM_SECRETS_DIR", None)
        else:
            os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = previous_secrets


def _run_real_evidence(argv, cwd: Path, stdout_path: Path):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if argv[2] == "content_platform":
        stdout_path.write_text(result.stdout, encoding="utf-8")
    return result


def _generate_evidence(source: Path, data: Path, name: str, runner=None) -> dict:
    evidence_root = data / "release-evidence" / name
    if evidence_root.exists():
        raise ReleaseAuditError(f"release evidence already exists: {evidence_root}")
    evidence_root.mkdir(parents=True)
    junit_path = evidence_root / "junit.xml"
    project_path = evidence_root / "project-audit.json"
    commands = [
        ("junit", [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit_path}"], junit_path),
        ("project_audit", [sys.executable, "-m", "content_platform", "project-audit"], project_path),
    ]
    records = []
    for kind, argv, output_path in commands:
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        result = (runner or _run_real_evidence)(argv, source, output_path)
        finished = dt.datetime.now(dt.timezone.utc).isoformat()
        records.append({
            "kind": kind,
            "argv": argv,
            "cwd": str(source),
            "started_at": started,
            "finished_at": finished,
            "returncode": result.returncode,
            "path": str(output_path),
            "sha256": _sha256(output_path) if output_path.is_file() else "",
        })
    manifest = {"commit": _git(source, "rev-parse", "HEAD").strip(), "evidence": records}
    manifest_path = evidence_root / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if any(record["returncode"] != 0 or not record["sha256"] for record in records):
        raise ReleaseAuditError(f"release evidence command failed: {manifest_path}")
    return {"manifest": manifest_path, "junit": junit_path, "project_audit": project_path}


def deploy_release(
    *,
    source_root: Path | str,
    releases_root: Path | str,
    current_link: Path | str | None = None,
    config_path: Path | str,
    test_report_path: Path | str | None = None,
    rollback_target: Path | str,
    data_root: Path | str,
    release_name: str | None = None,
    secrets_root: Path | str | None = None,
    signing_key: Path | str | None = None,
    project_audit_report: Path | str | None = None,
    min_tests: int = 900,
    evidence_runner=None,
) -> dict:
    """Deploy one clean source revision while holding the runtime release lock."""
    _validate_raw_path(source_root, "source_root")
    _validate_raw_path(releases_root, "releases_root")
    _validate_raw_path(config_path, "config_path")
    _validate_raw_path(rollback_target, "rollback_target")
    _validate_raw_path(data_root, "data_root")
    source = Path(source_root).expanduser().resolve()
    releases = Path(releases_root).expanduser().resolve()
    current = _current_path(current_link)
    config = Path(config_path).expanduser().resolve()
    rollback = Path(rollback_target).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if signing_key is not None:
        signing_key_path = Path(signing_key).expanduser().resolve()
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else signing_key_path.parent
    else:
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
        signing_key_path = secrets / "release-signing.key"
    _validate_signing_key_boundary(signing_key_path, secrets, data, releases, current)
    lock_path = data / "runtime-release.lock"

    with _exclusive_lock(lock_path):
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("source root is dirty or has uncommitted changes")
        commit = _git(source, "rev-parse", "HEAD").strip()
        rollback_rehearsal = _signed_rollback_dry_run(rollback, signing_key_path, secrets)
        name = release_name or commit[:12]
        evidence = _generate_evidence(source, data, name, runner=evidence_runner)
        report = evidence["junit"]
        project_audit_report_path = evidence["project_audit"]
        evidence_manifest_path = evidence["manifest"]
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ReleaseAuditError("release_name must be a single non-empty path component")
        release = releases / name
        if release.exists() or release.is_symlink():
            raise ReleaseAuditError(f"release already exists: {release}")
        releases.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=str(releases)))
        try:
            tracked_modes = _tracked_modes(source)
            for relative in _tracked_paths(source):
                source_path = source / relative
                if source_path.is_symlink() or not source_path.is_file():
                    raise ReleaseAuditError(f"tracked source file is not a regular file: {relative}")
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
                destination.chmod(0o755 if tracked_modes.get(relative.as_posix()) == "100755" else 0o644)
            os.replace(temporary, release)
            temporary = None
            attestation = data / "release-attestations" / f"{name}.sha256"
            previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
            previous_data = os.environ.get("CONTENT_PLATFORM_DATA_DIR")
            previous_secrets = os.environ.get("CONTENT_PLATFORM_SECRETS_DIR")
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(release)
            os.environ["CONTENT_PLATFORM_DATA_DIR"] = str(data)
            os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = str(secrets)
            try:
                _validate_runtime_config(config, release, data, secrets)
                metadata = audit_release(
                    source_root=source,
                    release_root=release,
                    configured_script_root=release / "scripts",
                    config_path=config,
                    test_report_path=report,
                    rollback_target=rollback,
                    attestation_path=attestation,
                    signing_key_path=signing_key_path,
                    trusted_secrets_root=secrets,
                    project_audit_report_path=project_audit_report_path,
                    evidence_manifest_path=evidence_manifest_path,
                    min_tests=min_tests,
                )
                metadata["rollback_rehearsal"] = rollback_rehearsal
                write_metadata(metadata, release / "release-metadata.json", signing_key_path=signing_key_path)
            finally:
                if previous_root is None:
                    os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
                else:
                    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
                if previous_data is None:
                    os.environ.pop("CONTENT_PLATFORM_DATA_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_DATA_DIR"] = previous_data
                if previous_secrets is None:
                    os.environ.pop("CONTENT_PLATFORM_SECRETS_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = previous_secrets
            _freeze_release(release)
            _activate(current, release)
            return {
                "ok": True,
                "release_root": str(release),
                "metadata_path": str(release / "release-metadata.json"),
                "attestation_path": str(attestation),
                "signing_key_path": str(signing_key_path),
                "commit": commit,
            }
        except Exception:
            if release.exists() and not release.is_symlink():
                shutil.rmtree(release)
            raise
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)


def rollback_release(
    *,
    target_release: Path | str,
    current_link: Path | str | None = None,
    data_root: Path | str,
    signing_key: Path | str | None = None,
    secrets_root: Path | str | None = None,
) -> dict:
    """Verify an audited frozen release and atomically activate it as current."""
    _validate_raw_path(target_release, "target_release")
    _validate_raw_path(data_root, "data_root")
    target = Path(target_release).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    current = _current_path(current_link)
    if signing_key is not None:
        key = Path(signing_key).expanduser().resolve()
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else key.parent
    else:
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
        key = secrets / "release-signing.key"
    _validate_signing_key_boundary(key, secrets, data, target.parent, current, target)
    with _exclusive_lock(data / "runtime-release.lock"):
        metadata_path = target / "release-metadata.json"
        previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
        os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
        try:
            metadata = verify_metadata(
                metadata_path,
                current_release_root=target,
                signing_key_path=key,
                trusted_secrets_root=secrets,
            )
        finally:
            if previous_root is None:
                os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
            else:
                os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
        _activate(current, target)
        return {
            "ok": True,
            "operation": "rollback",
            "release_root": str(target),
            "metadata_path": str(metadata_path),
            "attestation_path": metadata["attestation_path"],
            "commit": metadata["commit"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", nargs="?", choices=("deploy", "rollback", "init-signing-key"), default="deploy")
    parser.add_argument("--source-root")
    parser.add_argument("--releases-root")
    parser.add_argument("--current-link")
    parser.add_argument("--config-path")
    parser.add_argument("--test-report-path")
    parser.add_argument("--rollback-target")
    parser.add_argument("--target-release")
    parser.add_argument("--data-root")
    parser.add_argument("--release-name")
    parser.add_argument("--secrets-root")
    parser.add_argument("--signing-key")
    parser.add_argument("--project-audit-report")
    parser.add_argument("--min-tests", type=int, default=900)
    args = parser.parse_args()
    if args.operation == "init-signing-key":
        if not args.secrets_root:
            parser.error("init-signing-key requires --secrets-root")
        print(init_signing_key(args.secrets_root))
        return 0
    if not args.data_root:
        parser.error("deploy/rollback requires --data-root")
    if args.operation == "rollback":
        if not args.target_release:
            parser.error("rollback requires --target-release")
        if not args.signing_key and not args.secrets_root:
            parser.error("rollback requires --signing-key or --secrets-root")
        result = rollback_release(
            target_release=args.target_release,
            current_link=args.current_link,
            data_root=args.data_root,
            signing_key=args.signing_key,
            secrets_root=args.secrets_root,
        )
    else:
        required = {
            "source_root": args.source_root,
            "releases_root": args.releases_root,
            "config_path": args.config_path,
            "rollback_target": args.rollback_target,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"deploy requires: {', '.join(missing)}")
        if not args.signing_key and not args.secrets_root:
            parser.error("deploy requires --signing-key or --secrets-root")
        result = deploy_release(
            source_root=args.source_root,
            releases_root=args.releases_root,
            current_link=args.current_link,
            config_path=args.config_path,
            test_report_path=None,
            rollback_target=args.rollback_target,
            data_root=args.data_root,
            release_name=args.release_name,
            secrets_root=args.secrets_root,
            signing_key=args.signing_key,
            project_audit_report=args.project_audit_report,
            min_tests=args.min_tests,
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
