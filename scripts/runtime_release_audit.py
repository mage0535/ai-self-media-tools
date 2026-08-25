"""Create and validate auditable runtime release metadata."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


class ReleaseAuditError(RuntimeError):
    """Raised when a runtime release cannot be trusted."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


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


def audit_release(
    *,
    source_root: Path | str,
    release_root: Path | str,
    configured_script_root: Path | str,
    config_path: Path | str | None = None,
    test_report_path: Path | str | None = None,
    rollback_target: str | None = None,
) -> dict:
    source = _resolve(source_root)
    release = _resolve(release_root)
    script_root = _resolve(configured_script_root)
    expected_script_root = (release / "scripts").resolve()
    if not source.is_dir() or not release.is_dir() or script_root != expected_script_root:
        raise ReleaseAuditError("source, release, and configured script roots do not match")

    _assert_clean(source)
    commit = _git(source, "rev-parse", "HEAD").strip()
    source_hashes = _tracked_hashes(source)
    metadata = {
        "commit": commit,
        "source_root": str(source),
        "release_root": str(release),
        "configured_script_root": str(script_root),
        "source_hashes": source_hashes,
        "source_hash": hashlib.sha256(
            "\n".join(f"{name}:{digest}" for name, digest in sorted(source_hashes.items())).encode()
        ).hexdigest(),
        "config_hash": _sha256(_resolve(config_path)) if config_path else None,
        "test_report": str(_resolve(test_report_path)) if test_report_path else None,
        "test_report_hash": _sha256(_resolve(test_report_path)) if test_report_path else None,
        "rollback_target": rollback_target,
    }
    return metadata


def write_metadata(metadata: dict, path: Path | str) -> Path:
    destination = _resolve(path)
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
    parser.add_argument("--config-path")
    parser.add_argument("--test-report-path")
    parser.add_argument("--rollback-target")
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
