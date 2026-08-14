#!/usr/bin/env python3
"""Fail-closed verification for Xiaohongshu user-only handoff packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from content_platform.xiaohongshu_policy import validate_recovery_strategy


GATE_VERSION = "xhs_manual_publish_gate_v2"
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MIN_IMAGES = 3


def _result(passed: bool, *failures: str) -> dict:
    return {
        "version": GATE_VERSION,
        "passed": passed,
        "gate": "xiaohongshu_manual_publish_only",
        "hard_gate": True,
        "failures": list(failures),
    }


def check_handoff_package(path: str) -> dict:
    package_path = Path(path)
    if not package_path.is_file():
        return _result(False, "handoff_package_not_found")
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _result(False, "handoff_package_invalid_json")
    if not isinstance(package, dict):
        return _result(False, "handoff_package_not_object")
    if str(package.get("publish_mode") or "").casefold() not in {"manual", "handoff", "user_manual"}:
        return _result(False, "publish_mode_not_manual")
    required = ("title", "body", "cover", "images", "manual_publish_guide")
    missing = [field for field in required if not package.get(field)]
    if missing:
        return _result(False, "handoff_fields_missing:" + ",".join(missing))
    images = package.get("images")
    if not isinstance(images, list) or len(images) < MIN_IMAGES:
        return _result(False, f"handoff_requires_at_least_{MIN_IMAGES}_images")
    for image in images:
        if isinstance(image, str):
            raw_path = image
        elif isinstance(image, dict):
            raw_path = image.get("path") or image.get("file") or ""
        else:
            raw_path = ""
        image_path = Path(str(raw_path))
        if not image_path.is_file() or image_path.suffix.casefold() not in ALLOWED_IMAGE_EXTS:
            return _result(False, "handoff_image_missing_or_invalid")
    cover = Path(str(package.get("cover") or ""))
    if not cover.is_file() or str(cover) not in {str(Path(item)) for item in images if isinstance(item, str)}:
        return _result(False, "handoff_cover_missing_or_not_in_images")
    if len(str(package.get("title") or "")) > 20:
        return _result(False, "title_exceeds_20")
    if len(str(package.get("body") or "").strip()) < 50:
        return _result(False, "body_too_short")
    topics = package.get("topics") or []
    if not isinstance(topics, list) or not topics or len(topics) > 6:
        return _result(False, "topics_missing_or_exceed_6")
    if len(str(package.get("manual_publish_guide") or "")) < 20:
        return _result(False, "manual_publish_guide_too_short")
    strategy_failures = validate_recovery_strategy(package.get("growth_strategy"))
    if strategy_failures:
        return _result(False, *strategy_failures)
    return _result(True)


def reject_auto(reason: str = "") -> dict:
    return _result(False, "auto_publish_forbidden" + (":" + reason if reason else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Xiaohongshu manual-handoff hard gate")
    parser.add_argument("--check")
    parser.add_argument("--reject-auto", action="store_true")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    result = reject_auto(args.reason) if args.reject_auto else check_handoff_package(args.check) if args.check else _result(False, "usage_required")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
