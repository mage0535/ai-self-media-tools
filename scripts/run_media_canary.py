#!/usr/bin/env python3
"""Probe an isolated final.mp4 without publishing or changing platform state."""

from __future__ import annotations

import argparse
import json

from content_platform.media_canary import probe_media_artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir")
    parser.add_argument("--output", default="media_canary_report.json")
    args = parser.parse_args()
    report = probe_media_artifact(args.artifact_dir)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "artifact_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
