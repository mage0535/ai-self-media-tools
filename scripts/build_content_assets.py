#!/usr/bin/env python3
"""Compile source content assets into deterministic runtime JSON."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.content_assets import compile_content_assets


def main() -> int:
    result = compile_content_assets(
        ROOT / "config" / "default_hooks.json",
        ROOT / "config" / "content_quality_reference_pack.json",
        ROOT / "config" / "content_assets",
    )
    print(result)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
