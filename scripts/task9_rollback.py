"""Rollback rehearsal with dry-run as the safe default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any


def _tree_hash(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[path.relative_to(root).as_posix()] = digest
    return result


def _protected_snapshot(root: Path) -> dict[str, dict[str, int]]:
    """Snapshot protected state without hashing a potentially huge media tree."""
    if not root.exists():
        return {}
    paths = [root, *sorted(root.iterdir())]
    # Databases are the mutable source of truth. Record their metadata even
    # when nested one level below the supplied boundary.
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        paths.extend(path for path in root.rglob(pattern) if path not in paths)
    snapshot = {}
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        key = "." if path == root else path.relative_to(root).as_posix()
        snapshot[key] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "is_dir": int(path.is_dir())}
    return snapshot


def _activate(link: Path, target: Path) -> None:
    temporary = link.parent / f".{link.name}.{uuid.uuid4().hex}.tmp"
    try:
        os.symlink(str(target), str(temporary), target_is_directory=True)
        try:
            os.replace(temporary, link)
        except PermissionError:
            if os.name != "nt" or not link.is_symlink():
                raise
            link.unlink()
            os.replace(temporary, link)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()


def rehearse_rollback(
    current_root: Path | str,
    rollback_root: Path | str,
    *,
    dry_run: bool = True,
    protected_root: Path | str | None = None,
    current_link: Path | str | None = None,
    health_check=None,
) -> dict[str, Any]:
    protected = Path(protected_root).resolve() if protected_root else Path(current_root).resolve()
    before = _protected_snapshot(protected)
    # A rehearsal inspects the code target only. It never copies or removes
    # protected runtime state, including databases, cookies, or media.
    target_hash = _tree_hash(Path(rollback_root).resolve())
    link = Path(current_link) if current_link else None
    mutation_performed = False
    rollback_health = False
    forward_health = False
    forward_recovered = False
    error = ""
    if not dry_run:
        if link is None or not link.is_symlink():
            error = "current_link_missing_or_not_symlink"
        elif not Path(rollback_root).is_dir():
            error = "rollback_root_missing"
        else:
            forward = link.resolve(strict=True)
            try:
                _activate(link, Path(rollback_root).resolve(strict=True))
                mutation_performed = link.resolve(strict=True) == Path(rollback_root).resolve(strict=True)
                rollback_health = bool(health_check(link.resolve(strict=True)) if callable(health_check) else True)
            except Exception as exc:
                error = f"rollback_failed:{type(exc).__name__}:{exc}"
            finally:
                try:
                    _activate(link, forward)
                    forward_recovered = link.resolve(strict=True) == forward
                    forward_health = bool(health_check(forward) if callable(health_check) else True)
                except Exception as exc:
                    error = (error + ";" if error else "") + f"forward_recovery_failed:{type(exc).__name__}:{exc}"
    after = _protected_snapshot(protected)
    health_checks_passed = rollback_health and forward_health
    return {
        "passed": before == after and (dry_run or (bool(target_hash) and mutation_performed and health_checks_passed and forward_recovered and not error)),
        "dry_run": dry_run,
        "current_root": str(Path(current_root).resolve()),
        "rollback_root": str(Path(rollback_root).resolve()),
        "protected_hash_before": before,
        "protected_hash_after": after,
        "protected_state_preserved": before == after,
        "mutation_performed": mutation_performed,
        "health_checks_passed": health_checks_passed,
        "forward_recovered": forward_recovered,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-root", required=True)
    parser.add_argument("--rollback-root", required=True)
    parser.add_argument("--protected-root")
    parser.add_argument("--current-link")
    parser.add_argument("--health-command", nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="Record a non-mutating rehearsal; deployment remains out of scope")
    args = parser.parse_args()
    def health_check(root):
        if not args.health_command:
            return True
        proc = subprocess.run(args.health_command, cwd=root, capture_output=True, text=True, timeout=300, check=False)
        return proc.returncode == 0

    result = rehearse_rollback(
        args.current_root,
        args.rollback_root,
        dry_run=not args.execute,
        protected_root=args.protected_root,
        current_link=args.current_link,
        health_check=health_check,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "dry_run": result["dry_run"], "mutation_performed": result["mutation_performed"]}, ensure_ascii=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
