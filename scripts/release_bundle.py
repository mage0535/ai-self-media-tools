import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.project_audit import audit_project


EXCLUDE_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".db", ".sqlite", ".sqlite3", ".log"}


def should_skip(path: Path):
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return True
    if path.suffix.casefold() in EXCLUDE_SUFFIXES:
        return True
    return False


def export_bundle(source: Path, target: Path):
    audit = audit_project(source)
    if not audit["ok"]:
        raise SystemExit(f"project audit failed: {audit['issues'][:3]}")
    target = target.resolve()
    source = source.resolve()
    if target.exists():
        shutil.rmtree(target)
    for path in source.rglob("*"):
        try:
            path.resolve().relative_to(target)
            continue
        except ValueError:
            pass
        if should_skip(path.relative_to(source)):
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    return {"ok": True, "source": str(source), "target": str(target)}


def main():
    parser = argparse.ArgumentParser(description="Export a clean publishable project bundle")
    parser.add_argument("--source", default=str(ROOT))
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    result = export_bundle(Path(args.source), Path(args.target))
    print(result)


if __name__ == "__main__":
    main()
