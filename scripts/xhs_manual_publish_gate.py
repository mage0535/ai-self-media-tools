#!/usr/bin/env python3
"""Fail-closed verification for Xiaohongshu user-only handoff packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# 2026-08-15 修复：直接运行缺 PYTHONPATH 时自动注入项目根（self-contained）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_platform.xiaohongshu_policy import validate_recovery_strategy


GATE_VERSION = "xhs_manual_publish_gate_v2"
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
REQUIRED_IMAGES = 6


def _result(passed: bool, *failures: str) -> dict:
    return {
        "version": GATE_VERSION,
        "passed": passed,
        "gate": "xiaohongshu_manual_publish_only",
        "hard_gate": True,
        "failures": list(failures),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.load()
            return int(image.width), int(image.height)
    except (OSError, UnidentifiedImageError, ValueError):
        return 0, 0


def _image_path(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("path") or item.get("file") or "")
    return ""


def _manifest_by_path(package: dict) -> dict[str, dict]:
    rows = package.get("image_manifest") or package.get("artifacts") or []
    by_path: dict[str, dict] = {}
    if not isinstance(rows, list):
        return by_path
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = _image_path(row)
        if not raw:
            continue
        try:
            by_path[str(Path(raw).expanduser().resolve())] = row
        except OSError:
            by_path[str(Path(raw))] = row
    return by_path


def _has_render_evidence(row: dict, digest: str) -> bool:
    evidence = row.get("render_evidence")
    return (
        isinstance(evidence, dict)
        and evidence.get("verified") is True
        and str(evidence.get("artifact_sha256") or "") == digest
        and bool(str(evidence.get("renderer") or "").strip())
    )


def _receipt_failures(package: dict, image_hashes: list[str]) -> list[str]:
    receipt = package.get("operator_delivery")
    if not isinstance(receipt, dict):
        return ["operator_delivery_receipt_missing"]
    failures = []
    if receipt.get("passed") is not True:
        failures.append("operator_delivery_receipt_failed")
    if receipt.get("text_sent") is not True:
        failures.append("operator_delivery_text_missing")
    sent = receipt.get("sent")
    if not isinstance(sent, list) or len(sent) < REQUIRED_IMAGES:
        failures.append("operator_delivery_images_incomplete")
    try:
        image_count = int(receipt.get("image_count"))
    except (TypeError, ValueError):
        image_count = -1
    if image_count != REQUIRED_IMAGES:
        failures.append("operator_delivery_image_count_mismatch")
    expected = receipt.get("expected_images")
    if not isinstance(expected, list) or [str(item) for item in expected] != [str(item) for item in package.get("images") or []]:
        failures.append("operator_delivery_expected_images_mismatch")
    delivered_hashes = receipt.get("delivered_image_sha256")
    if not isinstance(delivered_hashes, list) or delivered_hashes != image_hashes:
        failures.append("operator_delivery_image_hashes_mismatch")
    return failures


def check_handoff_package(path: str, *, require_operator_delivery: bool = True) -> dict:
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
    if not isinstance(images, list) or len(images) != REQUIRED_IMAGES:
        return _result(False, f"handoff_requires_exactly_{REQUIRED_IMAGES}_images")
    failures = []
    manifest = _manifest_by_path(package)
    image_hashes = []
    resolved_images = []
    for index, image in enumerate(images, 1):
        raw_path = _image_path(image)
        image_path = Path(str(raw_path)).expanduser()
        try:
            image_path = image_path.resolve()
        except OSError:
            pass
        resolved_images.append(str(image_path))
        if not image_path.is_file() or image_path.suffix.casefold() not in ALLOWED_IMAGE_EXTS:
            failures.append(f"xiaohongshu_card_{index}_unreadable")
            continue
        try:
            digest = _sha256_file(image_path)
            with image_path.open("rb") as handle:
                if not handle.read(8):
                    failures.append(f"xiaohongshu_card_{index}_unreadable")
                    continue
        except OSError:
            failures.append(f"xiaohongshu_card_{index}_unreadable")
            continue
        width, height = _image_dimensions(image_path)
        if not width or not height:
            failures.append(f"xiaohongshu_card_{index}_unreadable")
        image_hashes.append(digest)
        row = manifest.get(str(image_path), image if isinstance(image, dict) else {})
        expected = str(row.get("sha256") or row.get("content_sha256") or "").strip() if isinstance(row, dict) else ""
        if expected and expected != digest:
            failures.append(f"xiaohongshu_card_{index}_checksum_mismatch")
        if not str(row.get("source_url") or row.get("source") or "").startswith(("https://", "http://", "generated:")):
            failures.append(f"xiaohongshu_card_{index}_source_missing")
        if not str(row.get("license") or row.get("license_type") or row.get("rights") or "").strip():
            failures.append(f"xiaohongshu_card_{index}_license_missing")
        if not _has_render_evidence(row, digest):
            failures.append(f"xiaohongshu_card_{index}_render_evidence_missing")
    cover = Path(str(package.get("cover") or ""))
    try:
        cover = cover.expanduser().resolve()
    except OSError:
        pass
    if not cover.is_file() or str(cover) not in set(resolved_images):
        failures.append("handoff_cover_missing_or_not_in_images")
    else:
        width, height = _image_dimensions(cover)
        if not width or not height:
            failures.append("xiaohongshu_cover_unreadable")
        elif width * 4 != height * 3:
            failures.append("xiaohongshu_cover_not_3_to_4")
    if len(set(image_hashes)) != len(image_hashes):
        failures.append("xiaohongshu_card_sha256_not_unique")
    if len(str(package.get("title") or "")) > 20:
        failures.append("title_exceeds_20")
    if len(str(package.get("body") or "").strip()) < 50:
        failures.append("body_too_short")
    topics = package.get("topics") or []
    if not isinstance(topics, list) or not topics or len(topics) > 6:
        failures.append("topics_missing_or_exceed_6")
    if len(str(package.get("manual_publish_guide") or "")) < 20:
        failures.append("manual_publish_guide_too_short")
    strategy_failures = validate_recovery_strategy(package.get("growth_strategy"))
    if strategy_failures:
        failures.extend(strategy_failures)
    if require_operator_delivery:
        failures.extend(_receipt_failures(package, image_hashes))
    return _result(not failures, *failures)


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
