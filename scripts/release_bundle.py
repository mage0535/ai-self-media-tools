import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.project_audit import (
    FORBIDDEN_NAME_PATTERNS,
    IGNORED_EXACT,
    IGNORED_PARTS,
    audit_project,
)


EXCLUDE_PARTS = set(IGNORED_PARTS) | {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".db", ".sqlite", ".sqlite3", ".log"}


def should_skip(path: Path):
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return True
    if path.name in IGNORED_EXACT:
        return True
    lowered = path.as_posix().casefold()
    if any(re.search(pattern, lowered) for pattern in FORBIDDEN_NAME_PATTERNS):
        return True
    if path.suffix.casefold() in EXCLUDE_SUFFIXES:
        return True
    return False


def tracked_files(source: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def export_bundle(source: Path, target: Path):
    audit = audit_project(source)
    if not audit["ok"]:
        raise SystemExit(f"project audit failed: {audit['issues'][:3]}")
    target = target.resolve()
    source = source.resolve()
    if target.exists():
        shutil.rmtree(target)
    copied = 0
    for relative in tracked_files(source):
        if should_skip(relative):
            continue
        path = source / relative
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(target)
            continue
        except ValueError:
            pass
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    target_audit = audit_project(target)
    if not target_audit["ok"]:
        raise SystemExit(f"bundle audit failed: {target_audit['issues'][:3]}")
    return {"ok": True, "source": str(source), "target": str(target), "files": copied}


def main():
    parser = argparse.ArgumentParser(description="Export a clean publishable project bundle")
    parser.add_argument("--source", default=str(ROOT))
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    result = export_bundle(Path(args.source), Path(args.target))
    print(result)


if __name__ == "__main__":
    main()
