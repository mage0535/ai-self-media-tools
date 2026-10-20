"""Pixel-grounded final cover validation shared by every delivery path."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError


ALLOWED_LAYOUTS = {
    "character_showdown", "evidence_interface", "hero_conflict", "diagonal_split",
    "before_after", "checklist_poster", "magazine_story", "result_reveal", "premium_fintech",
}
VERTICAL = {"douyin", "douyin_ai", "douyin_pet", "tiktok", "kuaishou", "shipinhao"}

# Conservative release thresholds. Borderline OCR is sent to review, never passed.
MIN_GRAY_STD = 8.0
MIN_ENTROPY = 2.0
MIN_EDGE_DENSITY = 0.0015
MAX_EDGE_DENSITY = 0.24
MAX_DARK_BUSY_COMPLEXITY = 0.64
MAX_TEXT_BLOCKS = 8
MAX_INFORMATION_MODULES = 6
MAX_COMPETING_FOCI = 4
MIN_TITLE_RECALL = 0.55
MIN_OCR_CONFIDENCE = 45.0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_evidence(evidence: dict[str, Any] | str | Path | None) -> dict[str, Any]:
    if isinstance(evidence, dict):
        return evidence
    if isinstance(evidence, (str, Path)):
        try:
            payload = json.loads(Path(evidence).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _pixel_metrics(image: Image.Image) -> dict[str, float]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    gray = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    histogram = np.bincount(gray.astype(np.uint8).ravel(), minlength=256)
    probabilities = histogram[histogram > 0] / histogram.sum()
    entropy = float(-(probabilities * np.log2(probabilities)).sum())
    horizontal = np.abs(np.diff(gray, axis=1))
    vertical = np.abs(np.diff(gray, axis=0))
    edge_density = (float((horizontal > 18).mean()) + float((vertical > 18).mean())) / 2
    brightness = float(gray.mean() / 255.0)
    gray_std = float(gray.std())
    clipped = float(((gray < 5) | (gray > 250)).mean())
    score = min(1.0, (gray_std / 48.0 + entropy / 6.0 + edge_density / 0.06) / 3.0)

    # Background crush detection (overly dark or washed-out flat sheets)
    dark_mask = (gray < 38)
    crushed_dark_ratio = float(dark_mask.mean())
    dark_std = float(gray[dark_mask].std()) if dark_mask.sum() > 200 else 999.0

    light_mask = (gray > 220)
    crushed_light_ratio = float(light_mask.mean())
    light_std = float(gray[light_mask].std()) if light_mask.sum() > 200 else 999.0

    return {
        "brightness": round(brightness, 6),
        "gray_std": round(gray_std, 4),
        "entropy": round(entropy, 4),
        "edge_density": round(edge_density, 6),
        "clipped_pixel_ratio": round(clipped, 6),
        "visual_complexity": round(score, 6),
        "crushed_dark_ratio": round(crushed_dark_ratio, 6),
        "dark_std": round(dark_std, 4),
        "crushed_light_ratio": round(crushed_light_ratio, 6),
        "light_std": round(light_std, 4),
    }


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _title_from_evidence(evidence: dict[str, Any]) -> str:
    for field in ("title_cn", "title_en", "title", "hook"):
        value = str(evidence.get(field) or "").strip()
        if value:
            return value
    return ""


def _run_ocr(
    image: Image.Image,
    *,
    scale: str = "full",
    expected_text: str = "",
) -> dict[str, Any]:
    executable = shutil.which("tesseract")
    if not executable:
        return {"available": False, "words": [], "error": "tesseract_missing", "scale": scale}
    tessdata = next((root for root in (
        Path("/usr/share/tesseract-ocr/5/tessdata"), Path("/tmp/tessdata")
    ) if (root / "chi_sim.traineddata").is_file()), Path("/tmp/tessdata"))
    languages = "eng"
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    needs_chinese = any("\u4e00" <= char <= "\u9fff" for char in expected_text)
    if needs_chinese and (tessdata / "chi_sim.traineddata").is_file():
        env["TESSDATA_PREFIX"] = str(tessdata)
        languages = "chi_sim+eng"
    try:
        with tempfile.TemporaryDirectory(prefix="cover-ocr-") as directory:
            source = Path(directory) / "cover.png"
            output = Path(directory) / "ocr"
            image.save(source, format="PNG")
            completed = subprocess.run(
                [
                    executable, str(source), str(output), "-l", languages,
                    "--psm", "11", "-c", "tessedit_create_tsv=1",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                env=env,
            )
            tsv = output.with_suffix(".tsv")
            if completed.returncode != 0 or not tsv.is_file():
                return {
                    "available": False,
                    "words": [],
                    "error": f"tesseract_exit_{completed.returncode}",
                    "scale": scale,
                }
            rows = csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8", errors="replace")), delimiter="\t")
            words: list[dict[str, Any]] = []
            for row in rows:
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                try:
                    confidence = float(row.get("conf") or -1)
                    word = {
                        "text": text,
                        "confidence": confidence,
                        "left": int(row.get("left") or 0),
                        "top": int(row.get("top") or 0),
                        "width": int(row.get("width") or 0),
                        "height": int(row.get("height") or 0),
                        "block": int(row.get("block_num") or 0),
                        "line": int(row.get("line_num") or 0),
                    }
                except (TypeError, ValueError):
                    continue
                words.append(word)
            return {"available": True, "words": words, "error": "", "scale": scale}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "words": [], "error": str(exc), "scale": scale}


def _recall(expected: str, observed: str) -> float:
    expected_norm = _normalize_text(expected)
    observed_norm = _normalize_text(observed)
    if not expected_norm:
        return 0.0
    matched = sum(block.size for block in SequenceMatcher(None, expected_norm, observed_norm).get_matching_blocks())
    return min(1.0, matched / len(expected_norm))


def _group_ocr(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        if word["confidence"] >= 0 and _normalize_text(word["text"]):
            groups[(word["block"], word["line"])].append(word)
    lines: list[dict[str, Any]] = []
    for (block, line), items in groups.items():
        items.sort(key=lambda item: item["left"])
        left = min(item["left"] for item in items)
        top = min(item["top"] for item in items)
        right = max(item["left"] + item["width"] for item in items)
        bottom = max(item["top"] + item["height"] for item in items)
        lines.append({
            "block": block,
            "line": line,
            "text": " ".join(item["text"] for item in items),
            "confidence": sum(item["confidence"] for item in items) / len(items),
            "box": [left, top, right, bottom],
            "word_count": len(items),
        })
    return lines


def _rescale_ocr(ocr: dict[str, Any], factor: float) -> dict[str, Any]:
    if factor == 1.0:
        return ocr
    scaled = dict(ocr)
    scaled["words"] = [
        {
            **word,
            "left": int(round(word["left"] * factor)),
            "top": int(round(word["top"] * factor)),
            "width": int(round(word["width"] * factor)),
            "height": int(round(word["height"] * factor)),
        }
        for word in ocr.get("words") or []
    ]
    return scaled


def _ocr_metrics(ocr: dict[str, Any], expected_title: str, width: int, height: int) -> dict[str, Any]:
    words = list(ocr.get("words") or [])
    lines = _group_ocr(words)
    observed = " ".join(word["text"] for word in words)
    title_recall = _recall(expected_title, observed)
    title_lines = [line for line in lines if _recall(expected_title, line["text"]) >= MIN_TITLE_RECALL]
    title_boxes = [line["box"] for line in title_lines]
    title_confidence = (
        sum(line["confidence"] for line in title_lines) / len(title_lines)
        if title_lines else 0.0
    )
    block_ids = {word["block"] for word in words if word["confidence"] >= 35 and _normalize_text(word["text"])}
    information_modules = {
        line["block"] for line in lines
        if line["word_count"] >= 2 and line["box"][1] >= int(height * 0.18)
    }
    large_lines = [
        line for line in lines
        if line["box"][3] - line["box"][1] >= max(36, int(height * 0.022))
        and line["box"][2] - line["box"][0] >= int(width * 0.12)
    ]
    duplicate_title_count = sum(_recall(expected_title, line["text"]) >= 0.78 for line in lines)
    title_like_lines = [line for line in lines if _recall(expected_title, line["text"]) >= 0.45]
    low_confidence_title_like = len(title_like_lines) > 1 and any(
        line["confidence"] < 35 for line in title_like_lines
    )
    return {
        "available": bool(ocr.get("available")),
        "error": str(ocr.get("error") or ""),
        "recognized_text": observed,
        "word_count": len(words),
        "text_block_count": len(block_ids),
        "information_module_count": len(information_modules),
        "competing_focal_point_count": len(large_lines),
        "title_recall": round(title_recall, 4),
        "title_confidence": round(title_confidence, 2),
        "title_boxes": title_boxes,
        "duplicate_title_count": duplicate_title_count,
        "background_residual_suspected": low_confidence_title_like,
    }


def _safe_zone(width: int, height: int, title_boxes: list[list[int]]) -> dict[str, Any]:
    bounds = {
        "left": int(round(width * 0.04)),
        "top": int(round(height * 0.05)),
        "right": int(round(width * 0.96)),
        "bottom": int(round(height * 0.82)),
    }
    title_inside = bool(title_boxes) and all(
        left >= bounds["left"] and top >= bounds["top"]
        and right <= bounds["right"] and bottom <= bounds["bottom"]
        for left, top, right, bottom in title_boxes
    )
    return {
        "source": "ocr_geometry",
        "bounds": bounds,
        "title_boxes": title_boxes,
        "title_inside": title_inside,
    }


def _base_result(path: Path, failures: list[str], *, status: str = "fail") -> dict[str, Any]:
    return {"passed": False, "status": status, "cover": str(path), "failures": failures, "review_reasons": []}


def validate_cover(
    cover: str | Path,
    evidence: dict[str, Any] | str | Path | None,
    platform: str = "",
) -> dict[str, Any]:
    path = Path(cover)
    failures: list[str] = []
    review_reasons: list[str] = []
    if not path.is_file():
        return _base_result(path, ["cover_missing"])
    evidence_payload = _load_evidence(evidence)
    cover_sha256 = _file_sha256(path)
    background_provenance = evidence_payload.get("background_provenance")
    if not isinstance(background_provenance, dict):
        failures.append("background_provenance_missing")
    else:
        background_path = str(background_provenance.get("path") or "").strip()
        if not background_path:
            failures.append("background_provenance_path_missing")
        elif not Path(background_path).is_file():
            failures.append("background_source_missing")
        elif Path(background_path).resolve() == path.resolve():
            failures.append("cover_cannot_be_its_own_background")
        if background_provenance.get("visible_required") is not True:
            failures.append("background_visibility_contract_missing")
    if evidence_payload.get("independent_render") is not True:
        failures.append("independent_cover_render_missing")
    expected_sha = str(evidence_payload.get("cover_sha256") or "").casefold()
    if not expected_sha:
        failures.append("cover_sha256_missing")
    elif not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or expected_sha != cover_sha256:
        failures.append("cover_sha256_mismatch")
    try:
        with Image.open(path) as opened:
            image_format = str(opened.format or "").upper()
            image = opened.convert("RGB")
    except (OSError, UnidentifiedImageError):
        result = _base_result(path, ["cover_probe_failed"])
        result["cover_sha256"] = cover_sha256
        return result
    width, height = image.size
    if path.suffix.casefold() != ".png" or image_format != "PNG":
        failures.append("final_cover_must_be_png")
    normalized_platform = str(platform or evidence_payload.get("platform") or "").casefold()
    if min(width, height) < 1000:
        failures.append("cover_resolution_too_low")
    aspect = width / height
    if normalized_platform == "xiaohongshu":
        if abs(aspect - 3 / 4) > 0.02 and abs(aspect - 9 / 16) > 0.02:
            failures.append("xiaohongshu_cover_aspect_invalid")
    elif normalized_platform in VERTICAL and abs(aspect - 9 / 16) > 0.02:
        failures.append("vertical_cover_aspect_invalid")
    if evidence_payload.get("layout_key") not in ALLOWED_LAYOUTS:
        failures.append("viral_layout_missing")
    for field in ("hook", "conflict_or_payoff", "content_match_reason"):
        if not str(evidence_payload.get(field) or "").strip():
            failures.append(f"{field}_missing")
    if not evidence_payload.get("focal_subjects"):
        failures.append("focal_subjects_missing")
    if evidence_payload.get("degraded") is True:
        failures.append("degraded_cover_forbidden")

    pixel_metrics = _pixel_metrics(image)
    if (
        pixel_metrics["gray_std"] < MIN_GRAY_STD
        or pixel_metrics["entropy"] < MIN_ENTROPY
        or pixel_metrics["edge_density"] < MIN_EDGE_DENSITY
    ):
        failures.append("cover_visual_complexity_too_low")
    if pixel_metrics["edge_density"] > MAX_EDGE_DENSITY or (
        pixel_metrics["brightness"] < 0.12
        and pixel_metrics["edge_density"] > 0.02
        and pixel_metrics["visual_complexity"] > MAX_DARK_BUSY_COMPLEXITY
    ):
        failures.append("cover_visual_complexity_too_high")
    if pixel_metrics["brightness"] < 0.035 or pixel_metrics["brightness"] > 0.96:
        failures.append("cover_brightness_out_of_range")
    if pixel_metrics.get("crushed_dark_ratio", 0) > 0.45 and pixel_metrics.get("dark_std", 999.0) < 10.0:
        failures.append("background_crushed_to_solid")
    if pixel_metrics.get("crushed_light_ratio", 0) > 0.45 and pixel_metrics.get("light_std", 999.0) < 10.0:
        failures.append("background_crushed_to_solid")

    background_provenance = evidence_payload.get("background_provenance")
    if isinstance(background_provenance, dict):
        background_path = str(background_provenance.get("path") or "").strip()
        if background_path and Path(background_path).is_file():
            try:
                with Image.open(background_path) as bg_img:
                    bg_rgb = bg_img.convert("RGB").resize(image.size, Image.Resampling.BILINEAR)
                    bg_gray = (
                        0.2126 * np.asarray(bg_rgb, dtype=np.float32)[:, :, 0]
                        + 0.7152 * np.asarray(bg_rgb, dtype=np.float32)[:, :, 1]
                        + 0.0722 * np.asarray(bg_rgb, dtype=np.float32)[:, :, 2]
                    )
                    img_gray = (
                        0.2126 * np.asarray(image, dtype=np.float32)[:, :, 0]
                        + 0.7152 * np.asarray(image, dtype=np.float32)[:, :, 1]
                        + 0.0722 * np.asarray(image, dtype=np.float32)[:, :, 2]
                    )
                    if bg_gray.mean() > 50.0:
                        non_text_mask = (img_gray < 200.0)
                        if non_text_mask.sum() > 1000:
                            retention = float(img_gray[non_text_mask].mean() / bg_gray[non_text_mask].mean())
                            if retention < 0.38:
                                failures.append("heavy_overlay_suppressed_background")
            except Exception:
                pass

    expected_title = _title_from_evidence(evidence_payload)
    if not expected_title:
        failures.append("expected_title_missing")

    if failures:
        skipped = {"available": False, "words": [], "error": "skipped_due_to_hard_failure"}
        ocr_metrics = _ocr_metrics(skipped, expected_title, width, height)
        thumbnail_metrics = _ocr_metrics(skipped, expected_title, 270, 480)
        safe_zone = _safe_zone(width, height, [])
    else:
        analysis_scale = min(1.0, 960.0 / max(width, height))
        analysis_image = image if analysis_scale == 1.0 else image.resize(
            (round(width * analysis_scale), round(height * analysis_scale)),
            Image.Resampling.LANCZOS,
        )
        full_ocr = _rescale_ocr(
            _run_ocr(analysis_image, scale="full", expected_text=expected_title),
            1.0 / analysis_scale,
        )
        ocr_metrics = _ocr_metrics(full_ocr, expected_title, width, height)
        safe_zone = _safe_zone(width, height, ocr_metrics["title_boxes"])
        if width >= height:
            thumb_w = 480
            thumb_h = max(1, int(round(480 * height / width)))
        else:
            thumb_w = 270
            thumb_h = 480
        thumbnail = image.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        thumbnail_ocr = _run_ocr(thumbnail, scale="thumbnail", expected_text=expected_title)
        thumbnail_metrics = _ocr_metrics(thumbnail_ocr, expected_title, thumb_w, thumb_h)

        if not full_ocr.get("available") or not thumbnail_ocr.get("available"):
            review_reasons.append("ocr_unavailable")
        else:
            if ocr_metrics["title_recall"] < MIN_TITLE_RECALL:
                failures.append("title_ocr_recall_too_low")
            elif ocr_metrics["title_confidence"] < MIN_OCR_CONFIDENCE:
                review_reasons.append("ocr_confidence_low")
            if thumbnail_metrics["title_recall"] < MIN_TITLE_RECALL:
                failures.append("thumbnail_title_unreadable")
            elif thumbnail_metrics["title_confidence"] < MIN_OCR_CONFIDENCE:
                review_reasons.append("thumbnail_ocr_confidence_low")
            if ocr_metrics["title_boxes"] and not safe_zone["title_inside"]:
                failures.append("title_outside_safe_zone")
            if ocr_metrics["duplicate_title_count"] > 1 or ocr_metrics["background_residual_suspected"]:
                failures.append("duplicate_or_background_text")
            is_landscape = (width > height or normalized_platform in {"zhihu", "bilibili", "youtube"})
            max_text_blocks = 14 if is_landscape else (10 if (evidence_payload.get("layout_key") == "premium_fintech" and evidence_payload.get("semantic_subject")) else MAX_TEXT_BLOCKS)
            if ocr_metrics["text_block_count"] > max_text_blocks:
                failures.append("text_block_count_too_high")
            max_info_modules = 9 if is_landscape else MAX_INFORMATION_MODULES
            if ocr_metrics["information_module_count"] > max_info_modules:
                failures.append("information_module_count_too_high")
            max_competing_foci = 8 if is_landscape else (7 if (evidence_payload.get("layout_key") == "premium_fintech" and evidence_payload.get("semantic_subject")) else (5 if evidence_payload.get("layout_key") == "premium_fintech" else MAX_COMPETING_FOCI))
            if ocr_metrics["competing_focal_point_count"] > max_competing_foci:
                failures.append("competing_focal_points")
            if evidence_payload.get("layout_key") == "premium_fintech" and evidence_payload.get("semantic_subject"):
                if ocr_metrics["title_recall"] < 0.70 or thumbnail_metrics["title_recall"] < 0.70:
                    failures.append("semantic_cover_title_recall_too_low")

    failures = list(dict.fromkeys(failures))
    review_reasons = list(dict.fromkeys(review_reasons))
    status = "fail" if failures else "review_required" if review_reasons else "pass"
    return {
        "passed": status == "pass",
        "status": status,
        "cover": str(path),
        "cover_sha256": cover_sha256,
        "dimensions": [width, height],
        "layout_key": evidence_payload.get("layout_key"),
        "pixel_metrics": pixel_metrics,
        "ocr": ocr_metrics,
        "thumbnail_ocr": thumbnail_metrics,
        "safe_zone": safe_zone,
        "failures": failures,
        "review_reasons": review_reasons,
    }


def lint_visual_template_css(content: str) -> list[str]:
    """
    Statically inspect CSS/HTML templates for toxic patterns that destroy background texture.
    Rejects full-canvas dark overlays exceeding 0.50 opacity or flat synthetic backdrops.
    """
    failures: list[str] = []
    heavy_rgba_pattern = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9]*\.?[0-9]+)\s*\)", re.I)
    for match in heavy_rgba_pattern.finditer(content):
        r, g, b, alpha = int(match.group(1)), int(match.group(2)), int(match.group(3)), float(match.group(4))
        if r < 45 and g < 45 and b < 45 and alpha >= 0.55:
            failures.append(f"heavy_dark_overlay_forbidden: rgba({r},{g},{b},{alpha}) exceeds 0.50 opacity limit")
            break

    if re.search(r"background:\s*#(?:0[0-7]){3}\b", content, re.I):
        failures.append("flat_near_black_solid_background_forbidden")

    return failures
