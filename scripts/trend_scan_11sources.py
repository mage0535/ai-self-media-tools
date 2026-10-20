#!/usr/bin/env python3
"""CLI wrapper for 11-source cross-platform trend scan."""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from content_platform.trend_scanner_11sources import run_11_sources_trend_scan


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan 11 platforms for viral trend evidence.")
    parser.add_argument("--keyword", default="猫咪", help="Keyword for domestic search")
    parser.add_argument("--proxy", default="socks5://127.0.0.1:2080", help="Proxy for foreign platforms")
    parser.add_argument("--output", help="Optional path to output json")
    args = parser.parse_args()

    result = run_11_sources_trend_scan(keyword=args.keyword, proxy=args.proxy)
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
        print(f"11-source trend matrix saved to {out_p}")
    else:
        print(output_json)

    # 11-source strict check: require at least 8 successful sources for resilient validation
    if result["successful_count"] < 8:
        print(f"Error: only {result['successful_count']}/11 sources succeeded, minimum 8 required for robust 11-source matrix.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
