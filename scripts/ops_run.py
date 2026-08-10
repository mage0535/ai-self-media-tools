#!/usr/bin/env python3
"""Create and validate a small run manifest before content generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.ops_run import create_run, record_topic
from content_platform.paths import project_home


def main() -> int:
    parser = argparse.ArgumentParser(description="Record topic-direction evidence for a content operations run.")
    parser.add_argument("date")
    parser.add_argument("--root", default="")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--platform", default="")
    parser.add_argument("--topic", default="")
    parser.add_argument("--direction", default="")
    parser.add_argument("--follow-up-to", default="")
    parser.add_argument("--difference-angle", default="")
    parser.add_argument("--recap-reason", default="")
    args = parser.parse_args()
    root = Path(args.root) if args.root else project_home()
    if args.init:
        print(json.dumps(create_run(root, args.date), ensure_ascii=False, indent=2))
        return 0
    if not args.platform or not args.topic:
        parser.error("--platform and --topic are required unless --init is used")
    result = record_topic(root, args.date, args.platform, args.topic, direction=args.direction, follow_up_to=args.follow_up_to, difference_angle=args.difference_angle, recap_reason=args.recap_reason)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
