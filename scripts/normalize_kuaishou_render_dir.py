#!/usr/bin/env python3
"""Normalize Kuaishou render artifacts for legacy validators."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def normalize(render_dir: Path) -> dict:
    render_dir = render_dir.resolve()
    copies = 0
    for subdir, pattern in [("cards", "card_*.png"), ("tts", "tts_*.mp3"), ("segments", "seg_*.mp4")]:
        source_dir = render_dir / subdir
        if not source_dir.is_dir():
            continue
        for source in sorted(source_dir.glob(pattern)):
            target = render_dir / source.name
            if not target.exists() or source.stat().st_mtime > target.stat().st_mtime or source.stat().st_size != target.stat().st_size:
                shutil.copy2(source, target)
                copies += 1
    counts = {
        "cards": len(list(render_dir.glob("card_*.png"))),
        "tts": len(list(render_dir.glob("tts_*.mp3"))),
        "segments": len(list(render_dir.glob("seg_*.mp4"))),
    }
    return {"passed": all(value >= 7 for value in counts.values()), "render_dir": str(render_dir), "copied": copies, "counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy Kuaishou subdirectory artifacts to render root for validators.")
    parser.add_argument("render_dir")
    args = parser.parse_args()
    result = normalize(Path(args.render_dir))
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
