"""Rollback rehearsal with dry-run as the safe default."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def rehearse_rollback(current_root: Path | str, rollback_root: Path | str, *, dry_run: bool = True, protected_root: Path | str | None = None) -> dict[str, Any]:
    protected = Path(protected_root).resolve() if protected_root else Path(current_root).resolve()
    before = _tree_hash(protected)
    # A rehearsal inspects the code target only. It never copies or removes
    # protected runtime state, including databases, cookies, or media.
    target_hash = _tree_hash(Path(rollback_root).resolve())
    after = _tree_hash(protected)
    return {
        "passed": before == after and bool(Path(rollback_root).exists()) is bool(target_hash),
        "dry_run": dry_run,
        "current_root": str(Path(current_root).resolve()),
        "rollback_root": str(Path(rollback_root).resolve()),
        "protected_hash_before": before,
        "protected_hash_after": after,
        "protected_state_preserved": before == after,
        "mutation_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-root", required=True)
    parser.add_argument("--rollback-root", required=True)
    parser.add_argument("--protected-root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="Record a non-mutating rehearsal; deployment remains out of scope")
    args = parser.parse_args()
    result = rehearse_rollback(args.current_root, args.rollback_root, dry_run=not args.execute, protected_root=args.protected_root)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "dry_run": result["dry_run"], "mutation_performed": result["mutation_performed"]}, ensure_ascii=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
