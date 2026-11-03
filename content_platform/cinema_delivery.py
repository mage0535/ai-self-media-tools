"""Evidence gate shared by the main runner and external cinema renderers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .body_visual_gate import evaluate_body_visual, motion_blocks_delivery
from .scene_manifest import validate_rendered_duration, validate_scene_manifest


def validate_cinema_delivery(
    scene_manifest: dict[str, Any],
    video_probe: dict[str, Any],
    bgm_source: dict[str, Any],
    motion_evidence: dict[str, Any] | None = None,
    subtitle_evidence: dict[str, Any] | None = None,
    *,
    video_path: Any = None,
    motion_fallback: str | None = None,
) -> dict[str, Any]:
    """Reject externally rendered media that lacks the same delivery proof as the main pipeline."""
    failures: list[str] = []
    scene_gate = validate_scene_manifest(scene_manifest)
    if not scene_gate.get("passed"):
        failures.extend(scene_gate.get("failures") or [])
    duration_gate = validate_rendered_duration(scene_manifest, float(video_probe.get("duration_seconds") or 0))
    if not duration_gate.get("passed"):
        failures.append(str(duration_gate.get("failure") or "duration policy failed"))
    if float(video_probe.get("duration_seconds") or 0) <= 0:
        failures.append("video duration missing")
    if int(video_probe.get("width") or 0) <= 0 or int(video_probe.get("height") or 0) <= 0:
        failures.append("video dimensions missing")
    if int(video_probe.get("audio_streams") or 0) < 1:
        failures.append("video audio stream missing")
    if int(video_probe.get("sample_rate") or 0) != 44100 or int(video_probe.get("channels") or 0) != 2:
        failures.append("audio specification invalid")
    if not str(bgm_source.get("source") or "").strip():
        failures.append("bgm source missing")
    if not str(bgm_source.get("license") or "").strip():
        failures.append("bgm license missing")
    if not str(bgm_source.get("sha256") or bgm_source.get("fingerprint") or "").strip():
        failures.append("bgm fingerprint missing")
    if not str(bgm_source.get("fit_reason") or "").strip():
        failures.append("bgm fit reason missing")
    if not isinstance(motion_evidence, dict) or not motion_evidence.get("passed"):
        failures.append("motion evidence failed")
    if not isinstance(subtitle_evidence, dict) or not subtitle_evidence.get("passed"):
        failures.append("subtitle evidence failed")
    if motion_blocks_delivery(scene_manifest) or motion_blocks_delivery(
        {"motion_evidence": motion_evidence, "MOTION_FALLBACK": motion_fallback}
    ):
        failures.append("MOTION_FALLBACK_BLOCKS_QUALIFIED")
    candidate = video_path or (video_probe.get("path") if isinstance(video_probe, dict) else None) or (
        video_probe.get("output") if isinstance(video_probe, dict) else None
    )
    if candidate:
        visual = evaluate_body_visual(Path(candidate), platform=_cinema_platform(scene_manifest))
        for code in visual.get("failed_codes") or []:
            if code not in failures:
                failures.append(code)
    passed = not failures
    return {
        "passed": passed,
        "delivery_verdict": "pass" if passed else "fail",
        "qualified": passed,
        "failures": failures,
        "scene_manifest_gate": scene_gate,
        "duration_gate": duration_gate,
        "video_probe": video_probe,
        "motion_evidence": motion_evidence or {},
        "subtitle_evidence": subtitle_evidence or {},
    }


def _cinema_platform(scene_manifest: dict[str, Any]) -> str:
    if not isinstance(scene_manifest, dict):
        return "bilibili"
    if scene_manifest.get("platform"):
        return str(scene_manifest.get("platform"))
    platforms = scene_manifest.get("platforms") or []
    if isinstance(platforms, list) and platforms:
        return str(platforms[0])
    return "bilibili"
