#!/usr/bin/env python3
"""Validate the pre-generation manifest embedded in a content packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content_platform.preflight_manifest import validate_preflight_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate preflight_manifest evidence in a packet JSON.")
    parser.add_argument("packet", help="JSON packet produced before generation, upload, draft, or publish")
    parser.add_argument("--channel", default="", help="Expected channel key, for example wechat or kuaishou")
    args = parser.parse_args()

    path = Path(args.packet)
    if not path.is_file():
        print(json.dumps({"ok": False, "error": "packet_file_missing", "path": str(path)}, ensure_ascii=False))
        return 2
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "packet_json_invalid", "detail": str(exc)[:200]}, ensure_ascii=False))
        return 2

    result = validate_preflight_manifest(packet, args.channel or None)
    print(json.dumps({"ok": bool(result.get("passed")), **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
