#!/usr/bin/env python3
"""Validate a Kuaishou auto-workflow packet before upload/schedule."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.media_quality import validate_kuaishou_auto_packet


def _load_packet(path: Path) -> tuple[dict | None, dict | None]:
    if not path.is_file():
        return None, {"passed": False, "failed_dimensions": ["packet_file_missing"], "path": str(path)}
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, {"passed": False, "failed_dimensions": ["packet_json_invalid"], "error": str(exc)}
    if not isinstance(packet, dict):
        return None, {"passed": False, "failed_dimensions": ["packet_json_not_object"], "actual_type": type(packet).__name__}
    return packet, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", help="JSON packet produced before Kuaishou upload")
    parser.add_argument("--phase", choices=["preflight", "postcheck"], default="preflight")
    args = parser.parse_args()
    packet, error = _load_packet(Path(args.packet))
    if error:
        print(json.dumps(error, ensure_ascii=False, indent=2))
        return 2
    result = validate_kuaishou_auto_packet(packet, phase=args.phase)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
