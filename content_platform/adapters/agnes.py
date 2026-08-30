"""Deterministic Agnes capability planning and availability probe."""

from __future__ import annotations

from typing import Any

from ..agnes_provider import probe_agnes


def probe(capability: dict[str, Any], _inputs: dict[str, Any]) -> tuple[bool, str]:
    status = probe_agnes()
    return (True, "available") if status["available"] else (False, "agnes_api_key_missing")


def execute(inputs: dict[str, Any]) -> dict[str, Any]:
    capability = inputs.get("_capability") or {}
    capability_id = str(capability.get("id") or "")
    profile = inputs.get("content_profile") if isinstance(inputs.get("content_profile"), dict) else {}
    blueprint = inputs.get("content_blueprint") if isinstance(inputs.get("content_blueprint"), dict) else {}
    visual_treatment = str(profile.get("visual_treatment") or blueprint.get("visual_treatment") or "editorial")
    content_format = str(profile.get("content_format") or blueprint.get("content_format") or "")
    is_video = "video" in content_format
    selected = capability_id == "agnes_image_21_flash" or is_video and capability_id == "agnes_video_25_flash"
    reason = (
        "high-density image/edit provider selected for cinematic or editorial assets"
        if capability_id == "agnes_image_21_flash"
        else "fast 720P generative footage provider selected for cinematic source scenes"
    )
    evidence = {
        "capability_id": capability_id,
        "selected": selected,
        "selection_reason": reason,
        "visual_treatment": visual_treatment,
        "content_format": content_format,
        "provider_probe": probe_agnes(),
    }
    return {
        "version": "agnes_media_plan_v1",
        "status": "planned" if selected else "skipped",
        "evidence": evidence,
        "runtime_evidence": {"version": "runtime_evidence_v1", "capability_id": capability_id},
    }
