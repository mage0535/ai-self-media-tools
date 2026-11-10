"""Fail-closed body-frame checks for short-video and knowledge-video delivery.

Samples the encoded picture. A motion exemption or ``kf_freeze*`` fallback
cannot by itself produce ``PREFLIGHT=PASS``, ``delivery_verdict=pass``, or
``qualified``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np


BACKGROUND_EMPTY_OR_SOLID = "BACKGROUND_EMPTY_OR_SOLID"
TEXT_OVERFLOW_FRAME = "TEXT_OVERFLOW_FRAME"
SUBTITLE_LAYOUT_UNREADABLE = "SUBTITLE_LAYOUT_UNREADABLE"
MOTION_FALLBACK_BLOCKS_QUALIFIED = "MOTION_FALLBACK_BLOCKS_QUALIFIED"
BODY_VISUAL_EVIDENCE_MISSING = "BODY_VISUAL_EVIDENCE_MISSING"
# Ink transitions per pixel of frame width that a clipped text line shows (see analyze_frame).
TEXT_STROKE_DENSITY = 0.09
# MED82 (Magic 11-10 14:30 CST): subtitle readability is measured, not inferred from layout.
# Glyph height (white fill, outline excluded) / frame height; measured fill height is about 0.63 x the ASS font size.
# Portrait 2.0% derives from BBC Subtitle Guidelines 9:16 line height 3.9%; landscape 3.4% sits below the qualified
# 16:9 delivery (median 3.7%). Contrast is WCAG 2.1 SC 1.4.3 (4.5:1), fill vs outline ring or vs background.
SUBTITLE_MIN_GLYPH_PORTRAIT = 0.020
SUBTITLE_MIN_GLYPH_LANDSCAPE = 0.034
SUBTITLE_MIN_CONTRAST = 4.5
SUBTITLE_SAMPLE_SECONDS = 2.0
SUBTITLE_MAX_FRAMES = 60
SUBTITLE_MIN_DETECTED = 3

BODY_VISUAL_FAIL_CODES = (
    BACKGROUND_EMPTY_OR_SOLID,
    TEXT_OVERFLOW_FRAME,
    SUBTITLE_LAYOUT_UNREADABLE,
    MOTION_FALLBACK_BLOCKS_QUALIFIED,
    BODY_VISUAL_EVIDENCE_MISSING,
)

# Douyin account variants are the same delivery surface as douyin.
# rednote is the Xiaohongshu alias already used by the packet gates.
# Bilibili knowledge short and long packs use this same checker.
BODY_VISUAL_PLATFORMS = frozenset(
    {
        "douyin",
        "douyin_pet",
        "douyin_ai",
        "shipinhao",
        "kuaishou",
        "xiaohongshu",
        "rednote",
        "youtube",
        "tiktok",
        "bilibili",
    }
)

_SAMPLE_WIDTH = 540
_NESTED_RECORD_KEYS = ("render_manifest", "preflight", "preflight_manifest", "delivery", "video_artifact")
_EXEMPT_STATUSES = {"exempted", "exempt", "motion_exempted"}


def platform_requires_body_visual(platform: str) -> bool:
    name = str(platform or "").casefold().strip()
    if name in BODY_VISUAL_PLATFORMS:
        return True
    return name.startswith("douyin")


def motion_blocks_delivery(record: dict[str, Any] | None) -> bool:
    """True when a delivery candidate uses kf_freeze* or an explicit motion exemption."""
    if not isinstance(record, dict):
        return False
    blobs = [record]
    for key in _NESTED_RECORD_KEYS:
        nested = record.get(key)
        if isinstance(nested, dict):
            blobs.append(nested)
    return any(_blob_blocks_delivery(blob) for blob in blobs)


def preflight_handoff_failures(packet: dict[str, Any] | None) -> list[str]:
    """Codes that forbid PREFLIGHT=PASS for a handoff candidate.

    Missing pixel evidence is not invented here. Rendered delivery checks sample
    the mp4 and fail closed on their own. This function blocks records that
    already declare a freeze fallback, a motion exemption, or failed body-visual
    codes.
    """
    if not isinstance(packet, dict):
        return []
    codes: list[str] = []
    if motion_blocks_delivery(packet):
        codes.append(MOTION_FALLBACK_BLOCKS_QUALIFIED)
    blobs: list[dict[str, Any]] = [packet]
    for key in ("body_visual_gate", "body_visual", "render_manifest"):
        nested = packet.get(key)
        if isinstance(nested, dict):
            blobs.append(nested)
            inner = nested.get("body_visual")
            if isinstance(inner, dict):
                blobs.append(inner)
    for blob in blobs:
        for code in blob.get("failed_codes") or []:
            text = str(code)
            if text in BODY_VISUAL_FAIL_CODES and text not in codes:
                codes.append(text)
    return codes


def assess_handoff_preflight(record: dict[str, Any] | None) -> dict[str, Any]:
    codes = preflight_handoff_failures(record if isinstance(record, dict) else {})
    passed = not codes
    return {
        "preflight_status": "PASS" if passed else "FAIL",
        "passed": passed,
        "qualified": passed,
        "failed_codes": codes,
    }


def delivery_verdict(
    *,
    technical_passed: bool,
    body_visual: dict[str, Any] | None,
    motion_exempted: bool = False,
    motion_fallback: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Motion exemption is not a delivery pass. Body-visual codes fail closed."""
    codes: list[str] = []
    if not isinstance(body_visual, dict) or body_visual.get("passed") is not True:
        for code in (body_visual or {}).get("failed_codes") or []:
            text = str(code)
            if text not in codes:
                codes.append(text)
        if not codes:
            codes.append(BODY_VISUAL_EVIDENCE_MISSING)
    record: dict[str, Any] = {}
    if isinstance(manifest, dict):
        record.update(manifest)
    if motion_fallback:
        record["MOTION_FALLBACK"] = motion_fallback
    if motion_exempted:
        record["motion_exempted"] = True
    if motion_blocks_delivery(record) and MOTION_FALLBACK_BLOCKS_QUALIFIED not in codes:
        codes.append(MOTION_FALLBACK_BLOCKS_QUALIFIED)
    passed = bool(technical_passed) and not codes
    return {
        "delivery_verdict": "pass" if passed else "fail",
        "passed": passed,
        "qualified": passed,
        "preflight_status": "PASS" if passed else "FAIL",
        "failed_codes": codes,
    }


def evaluate_body_visual(video_path: Path | str, platform: str = "") -> dict[str, Any]:
    """Sample body frames from a final mp4 and return stable fail codes."""
    path = Path(video_path)
    if not path.is_file():
        return _empty_result(platform)
    try:
        duration = _probe_duration(path)
        frames = []
        for timestamp in _sample_times(duration):
            frame = _decode_frame(path, timestamp)
            if frame is not None:
                frames.append(frame)
        subtitle_frames = _decode_subtitle_frames(path, duration)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return _empty_result(platform)
    return evaluate_frames(frames, platform=platform, subtitle_frames=subtitle_frames)


def evaluate_frames(frames: list[Any], platform: str = "", subtitle_frames: list[Any] | None = None) -> dict[str, Any]:
    if not frames:
        return _empty_result(platform)
    reports = [analyze_frame(frame) for frame in frames]
    total = len(reports)
    codes: list[str] = []
    if _majority(sum(1 for row in reports if row["solid"]), total):
        codes.append(BACKGROUND_EMPTY_OR_SOLID)
    if _majority(sum(1 for row in reports if row["overflow"]), total):
        codes.append(TEXT_OVERFLOW_FRAME)
    readability = subtitle_readability(subtitle_frames) if subtitle_frames is not None else None
    if _majority(sum(1 for row in reports if row["subtitle_unreadable"]), total) or (readability or {}).get("unreadable"):
        codes.append(SUBTITLE_LAYOUT_UNREADABLE)
    result = {
        "passed": not codes,
        "failed_codes": codes,
        "platform": str(platform or "").casefold(),
        "frames_sampled": total,
        "frame_reports": reports,
        "evidence": "sampled_frames",
    }
    if readability is not None:
        result["subtitle_readability"] = readability
    return result


def _relative_luminance(rgb: Any) -> Any:
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _dilate(mask: Any, iterations: int) -> Any:
    mask = mask.copy()
    for _ in range(iterations):
        grown = mask.copy()
        grown[1:] |= mask[:-1]
        grown[:-1] |= mask[1:]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        mask = grown
    return mask


def measure_subtitle(rgb: Any) -> dict[str, Any] | None:
    """Measure the strongest white text line in the lower 40% of one full-resolution frame.

    Returns glyph height (fill rows only, outline excluded) and WCAG contrast of the fill against the
    outline ring (1-6 px around the glyphs) and against the band background (beyond 6 px); None when no
    subtitle-like line is found. Probe-grade: white text on a bright background can be missed.
    """
    frame = np.asarray(rgb)
    if frame.ndim != 3 or frame.shape[2] < 3 or frame.shape[0] < 64 or frame.shape[1] < 64:
        return None
    image = frame[:, :, :3].astype(np.int16)
    height, width = image.shape[:2]
    white = (image.mean(axis=2) > 200) & ((image.max(axis=2) - image.min(axis=2)) < 45)
    y0, x0, x1 = int(height * 0.60), int(width * 0.05), int(width * 0.95)
    transitions = np.abs(np.diff(white[y0:, x0:x1].astype(np.int8), axis=1)).sum(axis=1)
    best = None
    for start, end in _row_groups(np.where(transitions >= 8)[0], gap=3):
        rows = end - start + 1
        if rows < height * 0.008 or rows > height * 0.08:
            continue
        score = int(transitions[start : end + 1].sum())
        if best is None or score > best[2]:
            best = (start, end, score)
    if best is None:
        return None
    top, bottom = y0 + best[0], y0 + best[1]
    columns = np.where(white[top : bottom + 1, x0:x1].any(axis=0))[0]
    left, right = x0 + int(columns[0]), x0 + int(columns[-1])
    box = image[top : bottom + 1, left : right + 1]
    glyph = white[top : bottom + 1, left : right + 1]
    near = _dilate(glyph, 6)
    fill = float(_relative_luminance(box[glyph]).mean())
    ring_pixels = box[near & ~_dilate(glyph, 1)]
    background_pixels = box[~near]
    ring = float(np.median(_relative_luminance(ring_pixels))) if len(ring_pixels) else None
    background = float(np.median(_relative_luminance(background_pixels))) if len(background_pixels) > 20 else None
    return {
        "glyph_h_px": int(bottom - top + 1),
        "glyph_h_ratio": round((bottom - top + 1) / height, 4),
        "portrait": height > width,
        "contrast_vs_outline_ring": round((fill + 0.05) / (ring + 0.05), 2) if ring is not None else None,
        "contrast_vs_background": round((fill + 0.05) / (background + 0.05), 2) if background is not None else None,
    }


def subtitle_readability(frames: list[Any]) -> dict[str, Any]:
    """SUBTITLE_LAYOUT_UNREADABLE when most frames with a detected subtitle line are too small or too low-contrast.

    A clip with no detected subtitle (e.g. no burned captions) is not judged here.
    """
    rows = [row for row in (measure_subtitle(frame) for frame in frames) if row]
    for row in rows:
        minimum = SUBTITLE_MIN_GLYPH_PORTRAIT if row["portrait"] else SUBTITLE_MIN_GLYPH_LANDSCAPE
        contrast = max(value for value in (row["contrast_vs_outline_ring"], row["contrast_vs_background"], 0.0)
                       if value is not None)
        row["too_small"] = row["glyph_h_ratio"] < minimum
        row["low_contrast"] = contrast < SUBTITLE_MIN_CONTRAST
    bad = sum(1 for row in rows if row["too_small"] or row["low_contrast"])
    glyphs = sorted(row["glyph_h_ratio"] for row in rows)
    return {
        "frames": len(frames),
        "detected": len(rows),
        "unreadable_frames": bad,
        "glyph_h_ratio_median": glyphs[len(glyphs) // 2] if glyphs else None,
        "unreadable": len(rows) >= SUBTITLE_MIN_DETECTED and _majority(bad, len(rows)),
    }


def analyze_frame(rgb: Any) -> dict[str, Any]:
    """Classify one RGB frame.

    Thresholds are tuned on the rejected Douyin body cards (near-solid dark
    gray, full-bleed clipped text, short centered slogan chip) and checked
    against a real cover frame plus flat gray and darkened patterned scenes.
    """
    frame = np.asarray(rgb)
    if frame.ndim != 3 or frame.shape[2] < 3 or frame.shape[0] < 16 or frame.shape[1] < 16:
        return {
            "solid": False,
            "overflow": False,
            "subtitle_unreadable": False,
            "flat_fraction": 0.0,
            "saturation_mean": 0.0,
            "background_std": 0.0,
            "decodable": False,
        }
    pixels = frame[:, :, :3]
    height, width = pixels.shape[:2]
    luma = pixels.astype(np.float32).mean(axis=2)
    saturation = (pixels.max(axis=2).astype(np.int16) - pixels.min(axis=2).astype(np.int16)).astype(np.float32)
    dark = (saturation < 22) & (luma < 110)
    flat_fraction = float(dark.mean())
    saturation_mean = float(saturation.mean())
    background_std = float(luma[dark].std()) if bool(dark.any()) else 99.0
    solid = flat_fraction >= 0.80 and saturation_mean <= 20.0 and background_std <= 16.0

    bright = luma > 155
    dark_pixels = luma < 90
    row_bright = bright.mean(axis=1)
    row_dark = dark_pixels.mean(axis=1)
    text_rows = np.where((row_bright > 0.015) & (row_bright < 0.75) & (row_dark > 0.20))[0]
    overflow = False
    chips = False
    min_height = max(4, int(height * 0.006))
    max_height = int(height * 0.08)
    for start, end in _row_groups(text_rows):
        band_height = end - start + 1
        if band_height < min_height or band_height > max_height:
            continue
        band = luma[start : end + 1]
        # Ink is the minority tone of the band: light text on a dark card, or dark text on a light page
        # (on a light page the bright background, not the text, would span the width).
        ink = band > 155 if float((band > 155).mean()) < 0.5 else band < 90
        columns = np.where(ink.any(axis=0))[0]
        if len(columns) < 8:
            continue
        # Text strokes alternate many times along a row; an edge such as a dashboard, horizon or table rim
        # is a few long runs (measured 11-03: rejected cards 0.13-0.20, real footage edges 0.004-0.08).
        stroke_density = float(np.median(np.abs(np.diff(ink.astype(np.int8), axis=1)).sum(axis=1))) / width
        left = int(columns[0])
        right = int(columns[-1])
        width_fraction = (right - left + 1) / width
        left_gap = left / width
        right_gap = (width - 1 - right) / width
        full_bleed = width_fraction >= 0.90 and max(left_gap, right_gap) <= 0.045 and min(left_gap, right_gap) <= 0.02
        if full_bleed and stroke_density >= TEXT_STROKE_DENSITY:
            overflow = True
        centered_chip = (
            start >= int(height * 0.84)
            and 0.08 <= width_fraction <= 0.42
            and abs(left_gap - right_gap) <= 0.08
            and left_gap > 0.12
        )
        if centered_chip:
            chips = True
    subtitle_unreadable = chips and (solid or overflow)
    return {
        "solid": bool(solid),
        "overflow": bool(overflow),
        "subtitle_unreadable": bool(subtitle_unreadable),
        "flat_fraction": round(flat_fraction, 4),
        "saturation_mean": round(saturation_mean, 3),
        "background_std": round(background_std, 3),
        "decodable": True,
    }


def _empty_result(platform: str) -> dict[str, Any]:
    return {
        "passed": False,
        "failed_codes": [BODY_VISUAL_EVIDENCE_MISSING],
        "platform": str(platform or "").casefold(),
        "frames_sampled": 0,
        "frame_reports": [],
        "evidence": "missing",
    }


def _majority(hits: int, total: int) -> bool:
    return total > 0 and hits * 5 >= total * 3


def _row_groups(rows: Any, gap: int = 2) -> list[tuple[int, int]]:
    if len(rows) == 0:
        return []
    start = previous = int(rows[0])
    groups: list[tuple[int, int]] = []
    for value in rows[1:]:
        current = int(value)
        if current <= previous + gap:
            previous = current
            continue
        groups.append((start, previous))
        start = previous = current
    groups.append((start, previous))
    return groups


def _blob_blocks_delivery(blob: dict[str, Any]) -> bool:
    for key in ("MOTION_FALLBACK", "motion_fallback", "motion_mode"):
        if "kf_freeze" in str(blob.get(key) or "").casefold():
            return True
    if blob.get("motion_exempted") is True or blob.get("MOTION_EXEMPTED") is True:
        return True
    status = str(blob.get("motion_status") or blob.get("MOTION_STATUS") or "").casefold()
    if status in _EXEMPT_STATUSES:
        return True
    evidence = blob.get("motion_evidence")
    if isinstance(evidence, dict):
        if evidence.get("exempted") is True:
            return True
        evidence_status = str(evidence.get("status") or "").casefold()
        if evidence_status in _EXEMPT_STATUSES:
            return True
        fallback = str(evidence.get("fallback") or evidence.get("MOTION_FALLBACK") or evidence.get("motion_fallback") or "")
        if "kf_freeze" in fallback.casefold():
            return True
    return False


def _probe_duration(path: Path) -> float:
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if process.returncode != 0:
        return 0.0
    payload = json.loads(process.stdout or "{}")
    try:
        return float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _sample_times(duration: float) -> list[float]:
    """Skip the cover window on clips long enough to have a separate body."""
    if duration <= 0.2:
        return []
    if duration <= 4:
        start = min(0.05, duration / 2)
        end = max(start, duration - 0.05)
        count = 3
    else:
        start = min(2.5, duration * 0.4)
        end = max(start, duration - 0.25)
        count = 5
    if end <= start:
        return [start]
    return [round(start + (end - start) * index / (count - 1), 3) for index in range(count)]


def _decode_frame(path: Path, timestamp: float | None) -> Any | None:
    command = ["ffmpeg", "-v", "error"]
    if timestamp is not None:
        command.extend(["-ss", f"{timestamp:.3f}"])
    command.extend(
        [
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={_SAMPLE_WIDTH}:-2",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    process = subprocess.run(command, capture_output=True, timeout=30, check=False)
    raw = process.stdout or b""
    if process.returncode != 0 or len(raw) < _SAMPLE_WIDTH * 16 * 3:
        return None
    if len(raw) % (_SAMPLE_WIDTH * 3) != 0:
        return None
    height = len(raw) // (_SAMPLE_WIDTH * 3)
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, _SAMPLE_WIDTH, 3)
    return frame.copy()


def _probe_size(path: Path) -> tuple[int, int]:
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    streams = (json.loads(process.stdout or "{}").get("streams") or [{}]) if process.returncode == 0 else [{}]
    return int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)


def _decode_subtitle_frames(path: Path, duration: float) -> list[Any]:
    """Full-resolution frames every SUBTITLE_SAMPLE_SECONDS (at most SUBTITLE_MAX_FRAMES), for subtitle measurement."""
    width, height = _probe_size(path)
    if duration <= 0 or width < 64 or height < 64:
        return []
    if max(width, height) > 1920:  # ratios are scale-free; keep the work bounded
        factor = 1920 / max(width, height)
        width, height = int(width * factor) // 2 * 2, int(height * factor) // 2 * 2
    step = max(SUBTITLE_SAMPLE_SECONDS, duration / SUBTITLE_MAX_FRAMES)
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps=1/{step:.3f},scale={width}:{height}",
               "-frames:v", str(SUBTITLE_MAX_FRAMES), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    size = width * height * 3
    frames = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            while True:
                raw = process.stdout.read(size)
                if len(raw) < size:
                    break
                frames.append(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy())
        finally:
            process.stdout.close()
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
    return frames
