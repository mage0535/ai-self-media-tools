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
# systemd ExecStart paths must be explicit here: production releases are built
# from tracked files plus this manifest, while operational scripts can be
# intentionally untracked in a dirty working tree.
REQUIRED_RUNTIME_FILES = (
    Path("scripts/run_platform_hot_refresh.sh"),
    Path("scripts/run_wechat_blowup_refresh.sh"),
    Path("config/growth_strategy_distilled_per_account.md"),
    Path("config/growth_strategy_douyin_ai_20260821.md"),
)
RUNTIME_PACKAGE_DIRS = (Path("content_platform"),)
RUNTIME_CONFIG_DIRS = (Path("config"),)


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


def release_files(source: Path) -> list[Path]:
    """Return tracked files plus the small, explicit runtime dependency manifest."""
    files = set(tracked_files(source))
    for relative in REQUIRED_RUNTIME_FILES:
        path = source / relative
        if not path.is_file():
            raise SystemExit(f"required runtime file missing: {relative.as_posix()}")
        files.add(relative)
    for package_dir in RUNTIME_PACKAGE_DIRS:
        package_root = source / package_dir
        if not package_root.is_dir():
            raise SystemExit(f"required runtime package missing: {package_dir.as_posix()}")
        files.update(path.relative_to(source) for path in package_root.rglob("*.py"))
    for config_dir in RUNTIME_CONFIG_DIRS:
        config_root = source / config_dir
        if not config_root.is_dir():
            raise SystemExit(f"required runtime config directory missing: {config_dir.as_posix()}")
        files.update(path.relative_to(source) for path in config_root.rglob("*.json"))
    return sorted(files)


def export_bundle(source: Path, target: Path):
    """Copy tracked files, then audit exactly the files eligible for release."""
    target = target.resolve()
    source = source.resolve()
    if target.exists():
        shutil.rmtree(target)
    copied = 0
    for relative in release_files(source):
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
