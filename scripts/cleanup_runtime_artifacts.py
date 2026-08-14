#!/usr/bin/env python3
"""Archive only reconstructable aged media intermediates."""

import argparse
import json

from content_platform.runtime_hygiene import cleanup_runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly report candidates without moving files")
    args = parser.parse_args()
    print(json.dumps(cleanup_runtime(args.data_dir, retention_days=args.retention_days, dry_run=not args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
