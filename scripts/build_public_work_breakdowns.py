#!/usr/bin/env python3
"""Build the review-only public work breakdown artifact from an evidence bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_platform.public_work_breakdown import build_public_work_breakdowns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    target = Path(args.output)
    bundle = json.loads(source.read_text(encoding="utf-8"))
    report = build_public_work_breakdowns(bundle)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(target), **report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
