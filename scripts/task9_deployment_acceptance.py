"""Deployment acceptance wrapper; it never enables timers or deploys."""

from __future__ import annotations

import argparse
import json
import subprocess
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


def timers_are_safe(timer_states: dict[str, dict[str, object]]) -> bool:
    return bool(timer_states) and all(
        not bool(state.get("enabled")) and not bool(state.get("active"))
        for state in timer_states.values()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--current-root", required=True)
    parser.add_argument("--rollback-root", required=True)
    parser.add_argument("--protected-root", required=True)
    parser.add_argument("--current-link")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="Perform rollback, health checks, and forward recovery")
    parser.add_argument("--health-command", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    acceptance = evaluate_acceptance(report, repo_root=Path(__file__).resolve().parents[1])
    def health_check(root):
        if not args.health_command:
            return True
        process = subprocess.run(args.health_command, cwd=root, capture_output=True, text=True, timeout=300, check=False)
        return process.returncode == 0

    rollback = rehearse_rollback(
        args.current_root,
        args.rollback_root,
        dry_run=not args.execute,
        protected_root=args.protected_root,
        current_link=args.current_link,
        health_check=health_check,
    )
    try:
        timer_states = query_timer_states()
        timers_enabled = bool(timer_states) and all(state["enabled"] for state in timer_states.values())
        timers_safe = timers_are_safe(timer_states)
        timer_error = ""
    except Exception as exc:
        timer_states = {}
        timers_enabled = False
        timers_safe = False
        timer_error = str(exc)
    result = {
        "acceptance": acceptance,
        "rollback_rehearsal": rollback,
        "systemd_timers": timer_states,
        "timers_enabled": timers_enabled,
        "timers_safe": timers_safe,
        "timer_error": timer_error,
        "deployment_performed": False,
    }
    production_ready = acceptance["production_ready"] and rollback["passed"] and timers_safe
    result["production_ready"] = production_ready
    Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"production_ready": production_ready, "rollback_passed": rollback["passed"], "timers_safe": timers_safe}, ensure_ascii=True))
    return 0 if production_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
