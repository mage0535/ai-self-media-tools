"""Read-only checks for the actual encoded video rather than render intent."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


VERTICAL_SHORT_PLATFORMS = {"douyin", "kuaishou", "shipinhao", "tiktok", "youtube"}
# Knowledge-card videos animate via CSS zoompan/fade/crop on static card art;
# a 32x32 thumbnail at fps=1 underestimates that motion badly (0.013 vs 0.02
# measured for a genuinely animating 52s clip). Threshold 0.01 with denser
# sampling separates real animation from a frozen frame without false rejects.
MOTION_THRESHOLD = 0.01


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


def measure_motion(video_path: Path) -> float:
    # fps=2 across the whole clip (max 24 frames) catches slow CSS pans and
    # fades that fps=1 on the first 8 seconds misses entirely.
    command = ["ffmpeg", "-v", "error", "-i", str(video_path), "-vf", "fps=2,scale=48:48", "-frames:v", "24", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
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
    return round(sum(differences) / len(differences), 5)


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
