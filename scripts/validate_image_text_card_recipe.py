#!/usr/bin/env python3
"""Validate image-text card recipe evidence in a packet or recipe file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.content_recipe import validate_image_text_card_recipe


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate image_text_card_recipe evidence")
    parser.add_argument("path", help="JSON file containing image_text_card_recipe or a full content packet")
    args = parser.parse_args()
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    recipe = data.get("image_text_card_recipe") if isinstance(data, dict) else {}
    if not recipe and isinstance(data, dict) and str(data.get("version") or "") == "image_text_card_recipe_v1":
        recipe = data
    result = validate_image_text_card_recipe(recipe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
