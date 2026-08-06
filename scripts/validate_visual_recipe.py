#!/usr/bin/env python3
"""Validate a visual_recipe packet before video rendering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.video_recipe import load_effect_module_registry, validate_visual_recipe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate visual_recipe JSON")
    parser.add_argument("recipe", help="Path to visual_recipe.json or a plan.json containing visual_recipe")
    parser.add_argument("--registry", default=str(ROOT / "config" / "video_effect_modules.json"))
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.recipe).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": f"failed to read recipe: {type(exc).__name__}"}, ensure_ascii=False))
        return 2
    recipe = payload.get("visual_recipe") if isinstance(payload, dict) and "visual_recipe" in payload else payload
    registry = load_effect_module_registry(args.registry)
    result = validate_visual_recipe(recipe, registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
