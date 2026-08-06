"""Run the WeChat MP backend metrics refresh on the Hermes host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_platform.performance_cycle import _refresh_growth_strategies
from content_platform.performance_ingest import import_performance_file
from content_platform.store import Store
from scripts.wechat_mp_backend_collector import DEFAULT_OUTPUT, DEFAULT_PROFILE, collect


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/state.db")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--metrics-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=Path("data/performance/wechat_mp_daily_report.json"))
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    collection = collect(
        args.profile_dir,
        args.metrics_file,
        days=args.days,
        headless=True,
        state_file=args.state_file,
    )
    result = {"collection": collection, "import": None, "growth_strategy_refreshed": False}
    if collection.get("status") == "ok" and collection.get("records"):
        store = Store(args.db)
        result["import"] = import_performance_file(store, args.metrics_file, allow_unknown_job=True)
        _refresh_growth_strategies(store, ["wechat"])
        result["growth_strategy_refreshed"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if collection.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
