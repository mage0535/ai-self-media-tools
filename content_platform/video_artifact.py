"""Read-only checks for the actual encoded video rather than render intent."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


VERTICAL_SHORT_PLATFORMS = {"douyin", "kuaishou", "shipinhao", "tiktok", "youtube"}
MOTION_EVIDENCE_VERSION = "sustained-v2"
# Knowledge-card videos animate via CSS zoompan/fade/crop on static card art;
# a 32x32 thumbnail at fps=1 underestimates that motion badly (0.013 vs 0.02
# measured for a genuinely animating 52s clip). Threshold 0.01 with denser
# sampling separates real animation from a frozen frame without false rejects.
MOTION_THRESHOLD = 0.01
HIGH_QUALITY_MEAN_MOTION_THRESHOLD = 0.015
# Smooth camera movement can remain visibly continuous while each 0.5-second
# sample is below the stronger change threshold. Require both a broad low-level
# motion floor and enough stronger motion/peaks rather than mistaking it for a
# frozen image.
HIGH_QUALITY_SUSTAINED_MOTION_THRESHOLD = 0.003
HIGH_QUALITY_SUSTAINED_MOTION_RATIO_THRESHOLD = 0.85
HIGH_QUALITY_ACTIVE_RATIO_THRESHOLD = 0.20
HIGH_QUALITY_PEAK_DELTA = 0.025
HIGH_QUALITY_MIN_PEAKS = 2


def probe_video(video_path: Path) -> dict:
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(video_path)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "ffprobe failed")
    payload = json.loads(process.stdout)
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), {})
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration_seconds": round(float((payload.get("format") or {}).get("duration") or 0), 3),
    }


def motion_evidence_from_deltas(differences: list[float]) -> dict:
    """Evaluate real consecutive-frame deltas, not planned animation metadata."""
    if not differences:
        return {
            "passed": False,
            "mean_delta": 0.0,
            "active_ratio": 0.0,
            "sustained_motion_ratio": 0.0,
            "peak_count": 0,
            "static_ratio": 1.0,
        }
    ordered = sorted(differences)
    active = [value for value in differences if value >= MOTION_THRESHOLD]
    sustained = [value for value in differences if value >= HIGH_QUALITY_SUSTAINED_MOTION_THRESHOLD]
    peaks = [value for value in differences if value >= HIGH_QUALITY_PEAK_DELTA]
    mean_delta = sum(differences) / len(differences)
    p95_index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    active_ratio = len(active) / len(differences)
    sustained_motion_ratio = len(sustained) / len(differences)
    passed = (
        mean_delta >= HIGH_QUALITY_MEAN_MOTION_THRESHOLD
        and sustained_motion_ratio >= HIGH_QUALITY_SUSTAINED_MOTION_RATIO_THRESHOLD
        and active_ratio >= HIGH_QUALITY_ACTIVE_RATIO_THRESHOLD
        and len(peaks) >= HIGH_QUALITY_MIN_PEAKS
    )
    return {
        "passed": passed,
        "sample_count": len(differences),
        "mean_delta": round(mean_delta, 5),
        "p95_delta": round(ordered[p95_index], 5),
        "active_ratio": round(active_ratio, 5),
        "sustained_motion_ratio": round(sustained_motion_ratio, 5),
        "static_ratio": round(1 - active_ratio, 5),
        "peak_count": len(peaks),
    }


def measure_motion_evidence(video_path: Path) -> dict:
    # Sample all video sections at 2fps. A first-24-frame window misses late
    # static stretches and cannot prove a full cinematic timeline is active.
    command = ["ffmpeg", "-v", "error", "-i", str(video_path), "-vf", "fps=2,scale=48:48", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    process = subprocess.run(command, capture_output=True, timeout=60, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace").strip() or "ffmpeg motion sampling failed")
    frame_size = 48 * 48 * 3
    frames = [process.stdout[index : index + frame_size] for index in range(0, len(process.stdout), frame_size)]
    frames = [frame for frame in frames if len(frame) == frame_size]
    if len(frames) < 2:
        raise RuntimeError("insufficient frames for motion measurement")
    differences = []
    for left, right in zip(frames, frames[1:]):
        differences.append(sum(abs(a - b) for a, b in zip(left, right)) / (255 * frame_size))
    return motion_evidence_from_deltas(differences)


def measure_motion(video_path: Path) -> float:
    return float(measure_motion_evidence(video_path)["mean_delta"])


def _card_titles(render_manifest: dict) -> list[str]:
    titles = [str(item) for item in render_manifest.get("card_titles") or []]
    titles.extend(str(item.get("t") or item.get("title") or "") for item in render_manifest.get("cards") or [] if isinstance(item, dict))
    return [item.strip() for item in titles if item.strip()]


def verify_artifact(video_path: Path, render_manifest: dict, platform: str, *, probe: dict | None = None) -> dict:
    """Return structured checks. The function never writes, uploads, or modifies media."""
    video_path = Path(video_path)
    failures: list[str] = []
    if not video_path.is_file():
        failures.append("video_missing")
    try:
        media = probe or probe_video(video_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        media = {}
        failures.append("media_probe_failed")
    normalized_platform = str(platform or "").casefold()
    width, height = int(media.get("width") or 0), int(media.get("height") or 0)
    duration = float(media.get("duration_seconds") or 0)
    if normalized_platform in VERTICAL_SHORT_PLATFORMS and (width, height) != (1080, 1920):
        failures.append("vertical_resolution_invalid")
    if normalized_platform in VERTICAL_SHORT_PLATFORMS and duration > 60:
        failures.append("short_duration_exceeded")
    if any(re.fullmatch(r"scene\s+\d+", title, re.I) for title in _card_titles(render_manifest)):
        failures.append("placeholder_card_title")
    subtitle = render_manifest.get("subtitle") or {}
    if normalized_platform in VERTICAL_SHORT_PLATFORMS and (int(subtitle.get("width") or 0), int(subtitle.get("height") or 0)) != (1080, 1920):
        failures.append("subtitle_resolution_invalid")
    try:
        motion_score = float(render_manifest.get("motion_score")) if render_manifest.get("motion_score") is not None else measure_motion(video_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        motion_score = None
        failures.append("motion_measurement_failed")
    if motion_score is not None and motion_score < MOTION_THRESHOLD:
        failures.append("motion_evidence_insufficient")
    return {
        "passed": not failures,
        "platform": normalized_platform,
        "video_path": str(video_path),
        "probe": media,
        "motion_score": motion_score,
        "failed_dimensions": failures,
    }
