"""Create and validate auditable runtime release metadata."""

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import tempfile
from pathlib import Path


class ReleaseAuditError(RuntimeError):
    """Raised when a runtime release cannot be trusted."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _validate_raw_path(path: Path | str, label: str) -> None:
    original = Path(path).expanduser()
    if ".." in original.parts:
        raise ReleaseAuditError(f"{label} contains forbidden .. path component")
    current = Path(original.anchor) if original.is_absolute() else Path.cwd()
    parts = original.parts[1:] if original.anchor else original.parts
    if current.is_symlink():
        raise ReleaseAuditError(f"{label} path boundary is a symlink: {current}")
    for part in parts:
        if part in {"", "."}:
            continue
        current /= part
        if current.is_symlink():
            raise ReleaseAuditError(f"{label} path boundary is a symlink: {current}")


def _git(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_hashes(source_root: Path) -> dict[str, str]:
    output = _git(source_root, "ls-files", "-z")
    paths = [Path(item) for item in output.split("\0") if item]
    return {path.as_posix(): _sha256(source_root / path) for path in paths if (source_root / path).is_file()}


def _assert_clean(source_root: Path) -> None:
    if _git(source_root, "status", "--porcelain").strip():
        raise ReleaseAuditError("source root is dirty or has uncommitted changes")


def _assert_release_matches(source_root: Path, release_root: Path, source_hashes: dict[str, str]) -> None:
    for relative, expected in source_hashes.items():
        candidate = release_root / relative
        try:
            candidate.resolve(strict=True).relative_to(release_root)
        except (FileNotFoundError, ValueError) as exc:
            raise ReleaseAuditError(f"release tracked file resolves outside release root: {relative}") from exc
        if not candidate.is_file():
            raise ReleaseAuditError(f"release file missing: {relative}")
        actual = _sha256(candidate)
        if actual != expected:
            raise ReleaseAuditError(f"release content hash mismatch: {relative}")


def _assert_release_has_no_untracked_files(release_root: Path, source_hashes: dict[str, str]) -> None:
    tracked = set(source_hashes)
    for path in release_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(release_root)
        if path.name == "release-metadata.json":
            continue
        if relative.as_posix() not in tracked:
            raise ReleaseAuditError(f"release file is not tracked by source: {relative.as_posix()}")


def _assert_release_has_no_symlinks(release_root: Path) -> None:
    for root, directories, files in os.walk(release_root, followlinks=False):
        for name in (*directories, *files):
            candidate = Path(root) / name
            if candidate.is_symlink():
                raise ReleaseAuditError(f"release contains forbidden symlink: {candidate.relative_to(release_root)}")


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ReleaseAuditError(f"required evidence {label} does not exist: {path}")


def _validate_rollback_target(release_root: Path, rollback_target: Path) -> None:
    if not rollback_target.is_dir() or rollback_target == release_root:
        raise ReleaseAuditError("rollback target must be an existing directory different from current release")
    scripts = rollback_target / "scripts"
    if not scripts.is_dir():
        raise ReleaseAuditError("rollback target must contain runnable scripts")
    entries = [path for path in scripts.rglob("*") if path.is_file() and path.suffix.lower() in {".py", ".sh"}]
    if not entries:
        raise ReleaseAuditError("rollback target has no safe verifiable entrypoint")
    bash_entries = [entry for entry in entries if entry.suffix.lower() == ".sh"]
    bash_validator = None
    if bash_entries:
        configured_bash = os.environ.get("CONTENT_PLATFORM_BASH", "").strip()
        bash_validator = shutil.which(configured_bash or "bash")
        if not bash_validator and configured_bash and Path(configured_bash).is_file():
            bash_validator = configured_bash
        if not bash_validator:
            raise ReleaseAuditError("validator_unavailable: bash validator is not available")
    for entry in entries:
        if entry.suffix.lower() == ".py":
            temporary_pyc = tempfile.NamedTemporaryFile(suffix=".pyc", delete=False)
            temporary_pyc.close()
            try:
                py_compile.compile(str(entry), cfile=temporary_pyc.name, doraise=True)
            except py_compile.PyCompileError as exc:
                raise ReleaseAuditError(f"rollback Python entrypoint syntax error: {entry}") from exc
            finally:
                Path(temporary_pyc.name).unlink(missing_ok=True)
        else:
            try:
                result = subprocess.run([bash_validator, "-n", str(entry)], capture_output=True, text=True)
            except OSError as exc:
                raise ReleaseAuditError("validator_unavailable: bash validator could not be started") from exc
            if result.returncode != 0:
                raise ReleaseAuditError(f"rollback shell entrypoint syntax error: {entry}")


def audit_release(
    *,
    source_root: Path | str,
    release_root: Path | str,
    configured_script_root: Path | str,
    config_path: Path | str | None = None,
    test_report_path: Path | str | None = None,
    rollback_target: str | None = None,
) -> dict:
    if config_path is None or test_report_path is None or rollback_target is None:
        raise ReleaseAuditError("config_path, test_report_path, and rollback_target are required evidence")
    _validate_raw_path(source_root, "source_root")
    _validate_raw_path(release_root, "release_root")
    _validate_raw_path(configured_script_root, "configured_script_root")
    _validate_raw_path(config_path, "config_path")
    _validate_raw_path(test_report_path, "test_report_path")
    _validate_raw_path(rollback_target, "rollback_target")
    source = _resolve(source_root)
    release = _resolve(release_root)
    script_root = _resolve(configured_script_root)
    config = _resolve(config_path)
    test_report = _resolve(test_report_path)
    rollback = _resolve(rollback_target)
    expected_script_root = (release / "scripts").resolve()
    if not source.is_dir() or not release.is_dir() or script_root != expected_script_root:
        raise ReleaseAuditError("source, release, and configured script roots do not match")
    environment_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT", "").strip()
    if not environment_root:
        raise ReleaseAuditError("CONTENT_PLATFORM_CODE_ROOT is required")
    if _resolve(environment_root) != release:
        raise ReleaseAuditError("CONTENT_PLATFORM_CODE_ROOT does not match release code root")

    _assert_clean(source)
    _require_file(config, "config_path")
    _require_file(test_report, "test_report_path")
    commit = _git(source, "rev-parse", "HEAD").strip()
    source_hashes = _tracked_hashes(source)
    _assert_release_has_no_symlinks(release)
    _assert_release_matches(source, release, source_hashes)
    _assert_release_has_no_untracked_files(release, source_hashes)
    _validate_rollback_target(release, rollback)
    metadata = {
        "commit": commit,
        "source_root": str(source),
        "release_root": str(release),
        "configured_script_root": str(script_root),
        "source_hashes": source_hashes,
        "source_hash": hashlib.sha256(
            "\n".join(f"{name}:{digest}" for name, digest in sorted(source_hashes.items())).encode()
        ).hexdigest(),
        "config_hash": _sha256(config),
        "test_report": str(test_report),
        "test_report_hash": _sha256(test_report),
        "rollback_target": str(rollback),
    }
    return metadata


def write_metadata(metadata: dict, path: Path | str) -> Path:
    _validate_raw_path(path, "metadata_path")
    destination = _resolve(path)
    release = _resolve(metadata.get("release_root", ""))
    try:
        destination.relative_to(release)
    except ValueError as exc:
        raise ReleaseAuditError("metadata path must be inside release") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(metadata, handle, ensure_ascii=True, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ReleaseAuditError(f"release metadata already exists: {destination}") from exc
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--configured-script-root", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--test-report-path", required=True)
    parser.add_argument("--rollback-target", required=True)
    parser.add_argument("--metadata-path", required=True)
    args = parser.parse_args()
    metadata = audit_release(
        source_root=args.source_root,
        release_root=args.release_root,
        configured_script_root=args.configured_script_root,
        config_path=args.config_path,
        test_report_path=args.test_report_path,
        rollback_target=args.rollback_target,
    )
    print(write_metadata(metadata, args.metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
