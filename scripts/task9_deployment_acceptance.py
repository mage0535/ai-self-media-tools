"""Deployment acceptance wrapper; it never enables timers or deploys."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.task9_acceptance import evaluate_acceptance
from scripts.task9_rollback import rehearse_rollback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--current-root", required=True)
    parser.add_argument("--rollback-root", required=True)
    parser.add_argument("--protected-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="Still records only a non-mutating rehearsal")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    acceptance = evaluate_acceptance(report, repo_root=Path(__file__).resolve().parents[1])
    rollback = rehearse_rollback(args.current_root, args.rollback_root, dry_run=not args.execute, protected_root=args.protected_root)
    result = {"acceptance": acceptance, "rollback_rehearsal": rollback, "timers_enabled": False, "deployment_performed": False}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"production_ready": acceptance["production_ready"], "rollback_passed": rollback["passed"], "timers_enabled": False}, ensure_ascii=True))
    return 0 if acceptance["production_ready"] and rollback["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
