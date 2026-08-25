"""Build, attest, freeze, and atomically activate a versioned runtime release."""

import argparse
import contextlib
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
    _git,
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


def deploy_release(
    *,
    source_root: Path | str,
    releases_root: Path | str,
    current_link: Path | str | None = None,
    config_path: Path | str,
    test_report_path: Path | str,
    rollback_target: Path | str,
    data_root: Path | str,
    release_name: str | None = None,
    secrets_root: Path | str | None = None,
    signing_key: Path | str | None = None,
) -> dict:
    """Deploy one clean source revision while holding the runtime release lock."""
    _validate_raw_path(source_root, "source_root")
    _validate_raw_path(releases_root, "releases_root")
    _validate_raw_path(config_path, "config_path")
    _validate_raw_path(test_report_path, "test_report_path")
    _validate_raw_path(rollback_target, "rollback_target")
    _validate_raw_path(data_root, "data_root")
    source = Path(source_root).expanduser().resolve()
    releases = Path(releases_root).expanduser().resolve()
    current = _current_path(current_link)
    config = Path(config_path).expanduser().resolve()
    report = Path(test_report_path).expanduser().resolve()
    rollback = Path(rollback_target).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
    signing_key_path = Path(signing_key).expanduser().resolve() if signing_key is not None else data / "release-signing.key"
    lock_path = data / "runtime-release.lock"

    with _exclusive_lock(lock_path):
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("source root is dirty or has uncommitted changes")
        commit = _git(source, "rev-parse", "HEAD").strip()
        name = release_name or commit[:12]
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
                )
                write_metadata(metadata, release / "release-metadata.json")
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
) -> dict:
    """Verify an audited frozen release and atomically activate it as current."""
    _validate_raw_path(target_release, "target_release")
    _validate_raw_path(data_root, "data_root")
    target = Path(target_release).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    current = _current_path(current_link)
    with _exclusive_lock(data / "runtime-release.lock"):
        metadata_path = target / "release-metadata.json"
        previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
        os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
        try:
            metadata = verify_metadata(
                metadata_path,
                current_release_root=target,
                signing_key_path=signing_key,
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
    parser.add_argument("operation", nargs="?", choices=("deploy", "rollback"), default="deploy")
    parser.add_argument("--source-root")
    parser.add_argument("--releases-root")
    parser.add_argument("--current-link")
    parser.add_argument("--config-path")
    parser.add_argument("--test-report-path")
    parser.add_argument("--rollback-target")
    parser.add_argument("--target-release")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--release-name")
    parser.add_argument("--secrets-root")
    parser.add_argument("--signing-key")
    args = parser.parse_args()
    if args.operation == "rollback":
        if not args.target_release:
            parser.error("rollback requires --target-release")
        result = rollback_release(
            target_release=args.target_release,
            current_link=args.current_link,
            data_root=args.data_root,
            signing_key=args.signing_key,
        )
    else:
        required = {
            "source_root": args.source_root,
            "releases_root": args.releases_root,
            "config_path": args.config_path,
            "test_report_path": args.test_report_path,
            "rollback_target": args.rollback_target,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"deploy requires: {', '.join(missing)}")
        result = deploy_release(
            source_root=args.source_root,
            releases_root=args.releases_root,
            current_link=args.current_link,
            config_path=args.config_path,
            test_report_path=args.test_report_path,
            rollback_target=args.rollback_target,
            data_root=args.data_root,
            release_name=args.release_name,
            secrets_root=args.secrets_root,
            signing_key=args.signing_key,
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
