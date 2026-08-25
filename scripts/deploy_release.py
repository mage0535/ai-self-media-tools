"""Build, attest, freeze, and atomically activate a versioned runtime release."""

import argparse
import contextlib
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from scripts.runtime_release_audit import (
    ReleaseAuditError,
    _git,
    _validate_raw_path,
    audit_release,
    write_metadata,
)


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


def _freeze_release(release_root: Path) -> None:
    for path in sorted(release_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o555)
        elif path.is_file():
            path.chmod(0o444)
    release_root.chmod(0o555)


def _activate(current_link: Path, release_root: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    temporary = current_link.parent / f".{current_link.name}.{uuid.uuid4().hex}.tmp"
    try:
        os.symlink(str(release_root), str(temporary), target_is_directory=True)
        os.replace(temporary, current_link)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()


def deploy_release(
    *,
    source_root: Path | str,
    releases_root: Path | str,
    current_link: Path | str,
    config_path: Path | str,
    test_report_path: Path | str,
    rollback_target: Path | str,
    data_root: Path | str,
    release_name: str | None = None,
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
    current = Path(current_link).expanduser()
    config = Path(config_path).expanduser().resolve()
    report = Path(test_report_path).expanduser().resolve()
    rollback = Path(rollback_target).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
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
            for relative in _tracked_paths(source):
                source_path = source / relative
                if source_path.is_symlink() or not source_path.is_file():
                    raise ReleaseAuditError(f"tracked source file is not a regular file: {relative}")
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
            os.replace(temporary, release)
            temporary = None
            attestation = data / "release-attestations" / f"{name}.sha256"
            previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(release)
            try:
                metadata = audit_release(
                    source_root=source,
                    release_root=release,
                    configured_script_root=release / "scripts",
                    config_path=config,
                    test_report_path=report,
                    rollback_target=rollback,
                    attestation_path=attestation,
                )
                write_metadata(metadata, release / "release-metadata.json")
            finally:
                if previous_root is None:
                    os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
                else:
                    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
            _freeze_release(release)
            _activate(current, release)
            return {
                "ok": True,
                "release_root": str(release),
                "metadata_path": str(release / "release-metadata.json"),
                "attestation_path": str(attestation),
                "commit": commit,
            }
        except Exception:
            if release.exists() and not release.is_symlink():
                shutil.rmtree(release)
            raise
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--releases-root", required=True)
    parser.add_argument("--current-link", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--test-report-path", required=True)
    parser.add_argument("--rollback-target", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--release-name")
    args = parser.parse_args()
    print(deploy_release(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
