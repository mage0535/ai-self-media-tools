"""Deployment acceptance wrapper; it never enables timers or deploys."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.task9_acceptance import evaluate_acceptance
from scripts.task9_rollback import rehearse_rollback
from scripts.deploy_release import query_systemd_timer_states


def query_timer_states(timer_names: list[str] | None = None, systemd_runner=None) -> dict:
    names = timer_names or sorted(
        path.name for path in (ROOT / "systemd").glob("*.timer")
        if path.stem.startswith(("ai-self-media", "hermes-content-platform"))
    )
    if not names:
        raise RuntimeError("no ai-self-media systemd timers are defined")
    return query_systemd_timer_states(names, runner=systemd_runner)


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
    try:
        timer_states = query_timer_states()
        timers_enabled = bool(timer_states) and all(state["enabled"] for state in timer_states.values())
        timer_error = ""
    except Exception as exc:
        timer_states = {}
        timers_enabled = False
        timer_error = str(exc)
    result = {
        "acceptance": acceptance,
        "rollback_rehearsal": rollback,
        "systemd_timers": timer_states,
        "timers_enabled": timers_enabled,
        "timer_error": timer_error,
        "deployment_performed": False,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    production_ready = acceptance["production_ready"] and rollback["passed"] and timers_enabled
    print(json.dumps({"production_ready": production_ready, "rollback_passed": rollback["passed"], "timers_enabled": timers_enabled}, ensure_ascii=True))
    return 0 if production_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
