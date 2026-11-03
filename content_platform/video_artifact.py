"""Read-only checks for the actual encoded video rather than render intent."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

from .body_visual_gate import (
    BODY_VISUAL_FAIL_CODES,
    evaluate_body_visual,
    motion_blocks_delivery,
    platform_requires_body_visual,
)


VERTICAL_SHORT_PLATFORMS = {"douyin", "kuaishou", "shipinhao", "tiktok", "youtube"}
VERTICAL_RESOLUTION_OPTIONS = {
    "douyin": {(720, 1280), (1080, 1920)},
    "shipinhao": {(720, 1280), (1080, 1920)},
    "kuaishou": {(1080, 1920)},
    "tiktok": {(1080, 1920)},
    "youtube": {(1080, 1920)},
}
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
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,duration", "-of", "json", str(video_path)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "ffprobe failed")
    payload = json.loads(process.stdout)
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), {})
    video_duration = max([float((payload.get('format') or {}).get('duration') or 0)] +
        [float(item.get('duration') or 0) for item in payload.get('streams') or []])
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration_seconds": round(video_duration, 3),
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


def _exclude_short_global_transition_bursts(
    background_deltas: list[float],
    moving_area_ratios: list[float],
    *,
    sample_fps: int,
) -> dict:
    """Exclude only isolated <=0.75s full-frame transition bursts.

    Sustained coherent motion is never excluded; this keeps rejected camera
    oscillation samples failing while preventing hard cuts/xfades from
    contaminating scene-interior background statistics.
    """
    candidates = [
        background >= 0.025 and moving_area >= 0.10
        for background, moving_area in zip(background_deltas, moving_area_ratios)
    ]
    clusters: list[list[int]] = []
    excluded: set[int] = set()
    maximum_burst_samples = max(1, round(sample_fps * 0.75))
    index = 0
    while index < len(candidates):
        if not candidates[index]:
            index += 1
            continue
        end = index
        while end + 1 < len(candidates) and candidates[end + 1]:
            end += 1
        clusters.append([index, end])
        if end - index + 1 <= maximum_burst_samples:
            excluded.update(range(max(0, index - 1), min(len(candidates), end + 2)))
        index = end + 1
    return {
        "clusters": clusters,
        "excluded_indices": sorted(excluded),
        "maximum_burst_samples": maximum_burst_samples,
    }


def measure_spatial_motion_evidence(video_path: Path, *, sample_fps: int = 4) -> dict:
    """Separate edge-background motion from bounded central business motion.

    This intentionally measures encoded pixels. Renderer names and planned motion
    labels are not evidence that the background stayed still.
    """
    import numpy as np

    width, height = 180, 320
    command = [
        "ffmpeg", "-v", "error", "-i", str(video_path),
        "-vf", f"fps={sample_fps},scale={width}:{height}",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    process = subprocess.run(command, capture_output=True, timeout=120, check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace").strip() or "ffmpeg spatial motion sampling failed")
    frame_size = width * height
    raw_frames = [process.stdout[index:index + frame_size] for index in range(0, len(process.stdout), frame_size)]
    raw_frames = [frame for frame in raw_frames if len(frame) == frame_size]
    if len(raw_frames) < 8:
        raise RuntimeError("insufficient frames for spatial motion measurement")
    frames = [np.frombuffer(frame, dtype=np.uint8).reshape(height, width) for frame in raw_frames]

    background_mask = np.zeros((height, width), dtype=bool)
    # Use the true outer margin only. A 20px mask at this scale represented
    # 120px in the final frame and incorrectly included titles/business cards.
    edge = 8
    background_mask[55:240, :edge] = True
    background_mask[55:240, width - edge:] = True
    business_mask = np.zeros((height, width), dtype=bool)
    business_mask[52:248, 24:width - 24] = True

    background_deltas: list[float] = []
    business_deltas: list[float] = []
    moving_area_ratios: list[float] = []
    for left, right in zip(frames, frames[1:]):
        delta = np.abs(right.astype(np.int16) - left.astype(np.int16)).astype(np.float32) / 255.0
        background_deltas.append(float(delta[background_mask].mean()))
        business_deltas.append(float(delta[business_mask].mean()))
        moving_area_ratios.append(float((delta > 0.06).mean()))

    def percentile(values: list[float], q: float) -> float:
        return float(np.percentile(np.asarray(values, dtype=np.float32), q))

    transition_bursts = _exclude_short_global_transition_bursts(
        background_deltas,
        moving_area_ratios,
        sample_fps=sample_fps,
    )
    excluded_indices = set(transition_bursts["excluded_indices"])
    retained_indices = [index for index in range(len(background_deltas)) if index not in excluded_indices]
    if len(retained_indices) < 8:
        raise RuntimeError("insufficient non-transition frames for spatial motion measurement")
    retained_background = [background_deltas[index] for index in retained_indices]
    retained_business = [business_deltas[index] for index in retained_indices]
    retained_moving_area = [moving_area_ratios[index] for index in retained_indices]
    background_active_ratio = sum(value >= 0.006 for value in retained_background) / len(retained_background)
    business_active_ratio = sum(value >= 0.003 for value in retained_business) / len(retained_business)
    background_p95 = percentile(retained_background, 95)
    moving_area_p95 = percentile(retained_moving_area, 95)
    background_stable = background_active_ratio <= 0.15 and background_p95 <= 0.012
    failures: list[str] = []
    if not background_stable:
        failures.append("background_motion_forbidden")
    if moving_area_p95 > 0.25:
        failures.append("global_motion_area_excessive")
    if business_active_ratio < 0.05:
        failures.append("business_roi_motion_insufficient")
    return {
        "version": "spatial-motion-v2",
        "passed": not failures,
        "sample_fps": sample_fps,
        "sample_count": len(background_deltas),
        "background_stable": background_stable,
        "background_delta_p95": round(background_p95, 5),
        "background_active_ratio": round(background_active_ratio, 5),
        "business_roi_active_ratio": round(business_active_ratio, 5),
        "moving_area_ratio_p95": round(moving_area_p95, 5),
        "transition_clusters": transition_bursts["clusters"],
        "excluded_transition_samples": len(excluded_indices),
        "retained_sample_count": len(retained_indices),
        "failures": failures,
    }


def verify_final_pixels(video_path: Path, *, near_black_luminance: float = 8.0, max_dark_ratio: float = 0.995) -> dict:
    """Decode deterministic final-video samples and verify visible pixels.

    This is deliberately candidate-bound: all probe and pixel values come from
    ``video_path`` at call time. Manifest metadata is never used as a substitute.
    """
    video_path = Path(video_path).resolve()
    failures: list[str] = []
    if not video_path.is_file():
        return {"passed": False, "candidate_sha256": "", "samples": [], "failures": ["candidate_missing"]}
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    try:
        media = probe_video(video_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return {"passed": False, "candidate_sha256": digest, "samples": [], "failures": [f"candidate_probe_failed:{type(exc).__name__}"]}
    duration = float(media.get("duration_seconds") or 0.0)
    if duration <= 0:
        return {"passed": False, "candidate_sha256": digest, "samples": [], "failures": ["candidate_duration_invalid"]}
    timestamps = [0.04, max(0.04, duration * 0.5), max(0.04, duration - 0.15)]
    timestamps = list(dict.fromkeys(round(value, 3) for value in timestamps))
    samples: list[dict[str, object]] = []
    try:
        from PIL import Image, ImageStat
        for timestamp in timestamps:
            command = [
                "ffmpeg", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", str(video_path),
                "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
            ]
            process = subprocess.run(command, capture_output=True, timeout=45, check=False)
            if process.returncode or not process.stdout:
                failures.append(f"frame_decode_failed:{timestamp:.3f}")
                continue
            frame_sha = hashlib.sha256(process.stdout).hexdigest()
            with Image.open(io.BytesIO(process.stdout)) as image:
                rgb = image.convert("RGB")
                grayscale = rgb.convert("L")
                values = list(grayscale.getdata())
                mean_luminance = float(ImageStat.Stat(grayscale).mean[0])
                dark_ratio = sum(value <= near_black_luminance for value in values) / max(1, len(values))
                samples.append({
                    "timestamp": round(timestamp, 3),
                    "sha256": frame_sha,
                    "bytes": len(process.stdout),
                    "width": rgb.width,
                    "height": rgb.height,
                    "mean_luminance": round(mean_luminance, 3),
                    "dark_pixel_ratio": round(dark_ratio, 5),
                })
                if mean_luminance <= near_black_luminance or dark_ratio >= max_dark_ratio:
                    failures.append(f"near_black_frame:{timestamp:.3f}")
    except (OSError, RuntimeError, ValueError) as exc:
        failures.append(f"pixel_decode_failed:{type(exc).__name__}")
    if len(samples) != 3:
        failures.append("pixel_sample_count_insufficient")
    if len({str(item.get("sha256")) for item in samples}) < 2:
        failures.append("pixel_samples_identical")
    return {
        "version": "final-pixel-gate-v1",
        "passed": not failures,
        "candidate_path": str(video_path),
        "candidate_sha256": digest,
        "probe": media,
        "samples": samples,
        "failures": failures,
    }


def measure_motion(video_path: Path) -> float:
    return float(measure_motion_evidence(video_path)["mean_delta"])


def _card_titles(render_manifest: dict) -> list[str]:
    titles = [str(item) for item in render_manifest.get("card_titles") or []]
    titles.extend(str(item.get("t") or item.get("title") or "") for item in render_manifest.get("cards") or [] if isinstance(item, dict))
    return [item.strip() for item in titles if item.strip()]


def validate_duration_policy(platform: str, duration: float, render_manifest: dict) -> dict:
    """Short delivery is capped at 60s; long form needs a separate bound plan."""
    normalized = str(platform or "").casefold()
    normalized = {"douyin_ai": "douyin", "douyin_pet": "douyin",
                  "youtube_shorts": "youtube"}.get(normalized, normalized)
    failures = []
    long_form = False
    if duration <= 0:
        failures.append("video_duration_invalid")
    elif normalized in VERTICAL_SHORT_PLATFORMS and duration > 60:
        ref = render_manifest.get("long_form_plan_ref") or {}
        try:
            path = Path(str(ref.get("path") or ""))
            if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise ValueError('long_form_plan_path_untrusted')
            raw = path.read_bytes()
            plan = json.loads(raw)
            long_form = (
                isinstance(plan, dict)
                and hashlib.sha256(raw).hexdigest() == str(ref.get("sha256") or "")
                and plan.get("version") == "long_form_plan_v1"
                and str(plan.get("platform") or "").casefold() == normalized
                and plan.get("content_form") == "long_form"
                and float(plan.get("target_duration_seconds") or 0) >= duration
                and all(plan.get(key) for key in ("theme", "target_audience", "user_pain",
                    "opening_hook", "core_message", "voiceover", "subtitle_plan", "music_plan",
                    "ending_cta", "visual_alignment_plan"))
                and isinstance(plan.get("storyboard"), list)
                and len(plan["storyboard"]) >= 2
                and all(isinstance(row, dict) and row.get("voiceover")
                        and row.get("visual_asset") and row.get("match_reason")
                        for row in plan["storyboard"])
            )
        except (OSError, TypeError, ValueError, AttributeError):
            long_form = False
        if not long_form:
            failures.append("short_duration_exceeded")
    return {"passed": not failures, "actual_seconds": duration, "short_max_seconds": 60,
            "separately_declared_long_form": long_form, "failed_dimensions": failures}


def verify_artifact(video_path: Path, render_manifest: dict, platform: str, *, probe: dict | None = None) -> dict:
    """Return structured checks. The function never writes, uploads, or modifies media."""
    video_path = Path(video_path)
    failures: list[str] = []
    if not video_path.is_file():
        failures.append("video_missing")
    try:
        real_media = probe_video(video_path)
        media = real_media
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        media = probe if isinstance(probe, dict) else {}
        failures.append("media_probe_failed")
    normalized_platform = str(platform or "").casefold()
    width, height = int(media.get("width") or 0), int(media.get("height") or 0)
    duration = float(media.get("duration_seconds") or 0)
    valid_resolutions = VERTICAL_RESOLUTION_OPTIONS.get(normalized_platform, set())
    if normalized_platform in VERTICAL_SHORT_PLATFORMS and (width, height) not in valid_resolutions:
        failures.append("vertical_resolution_invalid")
    duration_policy = validate_duration_policy(normalized_platform, duration, render_manifest)
    failures.extend(duration_policy["failed_dimensions"])
    if any(re.fullmatch(r"scene\s+\d+", title, re.I) for title in _card_titles(render_manifest)):
        failures.append("placeholder_card_title")
    subtitle = render_manifest.get("subtitle") or {}
    subtitle_dimensions = (int(subtitle.get("width") or 0), int(subtitle.get("height") or 0))
    if normalized_platform in VERTICAL_SHORT_PLATFORMS and subtitle_dimensions != (width, height):
        failures.append("subtitle_resolution_invalid")
    try:
        motion_score = measure_motion(video_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        motion_score = None
        failures.append("motion_measurement_failed")
    if motion_score is not None and motion_score < MOTION_THRESHOLD:
        # Element animations use the existing native visual predicate, with
        # spatial measurements recomputed from these exact encoded pixels.
        element_motion_valid = False
        quality = render_manifest.get("render_quality_evidence") or {}
        if quality.get("motion_gate_mode") == "element_motion":
            try:
                from scripts.film_renderer import measure_spatial_motion_evidence
                from .video_release_runtime import _visual_failures
                measured_manifest = dict(render_manifest)
                measured_manifest["render_quality_evidence"] = dict(
                    quality, spatial_motion=measure_spatial_motion_evidence(video_path)
                )
                element_motion_valid = not _visual_failures(
                    measure_motion_evidence(video_path),
                    candidate_sha256=hashlib.sha256(video_path.read_bytes()).hexdigest(),
                    render_manifest=measured_manifest,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                element_motion_valid = False
        if not element_motion_valid:
            failures.append("motion_evidence_insufficient")
    final_pixel_gate = verify_final_pixels(video_path) if video_path.is_file() else {"passed": False, "failures": ["video_missing"]}
    failures.extend(str(item) for item in final_pixel_gate.get("failures") or [])
    body_visual = None
    if platform_requires_body_visual(normalized_platform):
        body_visual = evaluate_body_visual(video_path, platform=normalized_platform)
        for code in body_visual.get("failed_codes") or []:
            if code not in failures:
                failures.append(code)
        if motion_blocks_delivery(render_manifest) and "MOTION_FALLBACK_BLOCKS_QUALIFIED" not in failures:
            failures.append("MOTION_FALLBACK_BLOCKS_QUALIFIED")
    elif motion_blocks_delivery(render_manifest):
        failures.append("MOTION_FALLBACK_BLOCKS_QUALIFIED")
    passed = not failures
    result = {
        "passed": passed,
        "platform": normalized_platform,
        "video_path": str(video_path),
        "probe": media,
        "duration_policy": duration_policy,
        "motion_score": motion_score,
        "final_pixel_gate": final_pixel_gate,
        "failed_dimensions": failures,
    }
    if platform_requires_body_visual(normalized_platform) or any(code in BODY_VISUAL_FAIL_CODES for code in failures):
        result["body_visual"] = body_visual
        result["delivery_verdict"] = "pass" if passed else "fail"
        result["qualified"] = passed
        result["preflight_status"] = "PASS" if passed else "FAIL"
    return result
