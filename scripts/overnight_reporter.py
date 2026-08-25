#!/usr/bin/env python3
"""Print only newly consumed, human-readable overnight business updates."""

from __future__ import annotations

import argparse

from content_platform.chinese_reporter import ChineseReporter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--cursor", required=True)
    args = parser.parse_args()
    for message in ChineseReporter(args.events, args.cursor).consume():
        print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
