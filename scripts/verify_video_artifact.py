#!/usr/bin/env python3
"""Verify an encoded video and a renderer manifest before publisher handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.video_artifact import verify_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Check final-video dimensions, duration, titles, subtitles, and motion.")
    parser.add_argument("video")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--platform", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = verify_artifact(Path(args.video), manifest, args.platform)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
