#!/usr/bin/env python3
"""Validate that a cover is a topic-specific narrative poster, not a placeholder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


ALLOWED_LAYOUTS = {
    "character_showdown", "evidence_interface", "hero_conflict", "diagonal_split",
    "before_after", "checklist_poster", "magazine_story", "result_reveal",
}


def validate_cover(cover: Path, evidence_path: Path) -> dict:
    failures: list[str] = []
    if not cover.is_file() or not evidence_path.is_file():
        return {"passed": False, "failures": ["cover_or_evidence_missing"]}
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    width, height = Image.open(cover).size
    aspect = width / height
    platform = str(evidence.get("platform") or "")
    if width < 1000 or height < 1000:
        failures.append("cover_resolution_too_low")
    if platform in {"douyin_ai", "douyin_pet", "tiktok", "kuaishou", "xiaohongshu", "shipinhao"} and abs(aspect - 9 / 16) > 0.02:
        failures.append("vertical_cover_aspect_invalid")
    if evidence.get("layout_key") not in ALLOWED_LAYOUTS:
        failures.append("viral_layout_missing")
    for field in ["hook", "conflict_or_payoff", "content_match_reason"]:
        if not str(evidence.get(field) or "").strip():
            failures.append(f"{field}_missing")
    if not evidence.get("focal_subjects"):
        failures.append("focal_subjects_missing")
    if evidence.get("safe_zone_verified") is not True:
        failures.append("safe_zone_not_verified")
    if evidence.get("degraded") is True:
        failures.append("degraded_cover_forbidden")
    result = {
        "passed": not failures,
        "cover": str(cover),
        "dimensions": [width, height],
        "layout_key": evidence.get("layout_key"),
        "failures": failures,
    }
    evidence_path.with_name("cover_quality_gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cover", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_cover(Path(args.cover), Path(args.evidence))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
