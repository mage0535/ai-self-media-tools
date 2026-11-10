#!/usr/bin/env python3
"""List Kuaishou auto-posts that are scheduled but not yet live, for the kill-switch runbook.

Dry run by default and always: it reads ``autopublish_ledger.jsonl`` and prints each future
``published_pending_verification`` entry with its packet, so an operator can withdraw it in the
Kuaishou creator console (作品管理 / 待发布) before ``schedule_time``. Automated deletion is not
implemented: ``--confirm`` exits 3 rather than click anything untested on the live account.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "data" / "local_ops_kuaishou" / "autopublish_ledger.jsonl"


def pending(ledger: Path, now: datetime) -> list[dict]:
    rows = []
    if not ledger.is_file():
        return rows
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("decision") != "published_pending_verification" or not row.get("schedule_time"):
            continue
        when = datetime.strptime(str(row["schedule_time"]), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if when > now:
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--confirm", action="store_true", help="Not implemented; withdraw in the creator console.")
    args = parser.parse_args(argv)
    rows = pending(Path(args.ledger), datetime.now(ZoneInfo("Asia/Shanghai")))
    report = {"dry_run": True, "ledger": args.ledger, "pending_scheduled": rows,
              "manual_step": "creator console 作品管理 -> 待发布: delete each listed title before schedule_time"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.confirm:
        print(json.dumps({"ok": False, "error": "confirm_not_implemented"}, ensure_ascii=False), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
