#!/usr/bin/env python3
"""Verify an externally rendered cinema video before it becomes a handoff artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.cinema_delivery import validate_cinema_delivery


def _probe_video(video: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(video)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return {"error": (result.stderr or "ffprobe failed")[-300:]}
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video_stream = next((row for row in streams if row.get("codec_type") == "video"), {})
    return {
        "duration_seconds": float((payload.get("format") or {}).get("duration") or 0),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "audio_streams": sum(1 for row in streams if row.get("codec_type") == "audio"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--bgm-source", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    video = Path(args.video)
    scene_manifest = json.loads(Path(args.scene_manifest).read_text(encoding="utf-8-sig"))
    bgm_source = json.loads(Path(args.bgm_source).read_text(encoding="utf-8-sig"))
    result = validate_cinema_delivery(scene_manifest, _probe_video(video), bgm_source)
    result["video"] = str(video)
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
