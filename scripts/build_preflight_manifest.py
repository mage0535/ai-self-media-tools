#!/usr/bin/env python3
"""Build a canonical preflight_manifest JSON for content generation packets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content_platform.preflight_manifest import build_preflight_manifest, validate_preflight_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build content_preflight_manifest_v1 evidence.")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--content-type", required=True)
    parser.add_argument("--strategy-source", required=True)
    parser.add_argument("--strategy-result-path", required=True)
    parser.add_argument("--strategy-summary", required=True)
    parser.add_argument("--selected-topic", required=True)
    parser.add_argument("--selection-reason", required=True)
    parser.add_argument("--content-angle", required=True)
    parser.add_argument("--required-asset", action="append", default=[])
    parser.add_argument("--quality-gate", action="append", default=[])
    parser.add_argument("--extra-skill", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest = build_preflight_manifest(
        channel=args.channel,
        content_type=args.content_type,
        strategy_source=args.strategy_source,
        strategy_result_path=args.strategy_result_path,
        strategy_summary=args.strategy_summary,
        selected_topic=args.selected_topic,
        selection_reason=args.selection_reason,
        content_angle=args.content_angle,
        required_assets=args.required_asset,
        quality_gates=args.quality_gate or None,
        extra_skills=args.extra_skill,
    )
    probe_packet = {"platform": args.channel, "preflight_manifest": manifest}
    result = validate_preflight_manifest(probe_packet, args.channel)
    if not result.get("passed"):
        print(json.dumps({"ok": False, **result}, ensure_ascii=False, indent=2))
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "manifest_version": manifest["version"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
