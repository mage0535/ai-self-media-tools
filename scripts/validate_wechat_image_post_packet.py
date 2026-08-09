#!/usr/bin/env python3
"""Validate a WeChat Official Account image-message packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.media_quality import validate_wechat_image_post_packet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", help="JSON packet produced before WeChat image-message draft upload")
    args = parser.parse_args()
    path = Path(args.packet)
    if not path.is_file():
        print(json.dumps({"passed": False, "failed_dimensions": ["packet_file_missing"], "path": str(path)}, ensure_ascii=False, indent=2))
        return 2
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(json.dumps({"passed": False, "failed_dimensions": ["packet_json_invalid"], "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    result = validate_wechat_image_post_packet(packet)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
