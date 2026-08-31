"""Fail-closed checks for evidence that must exist before model generation."""

from __future__ import annotations

import os
from typing import Any

from .artifact_contract import required_artifact_kinds
from .content_policy import DELIVERY_PUBLISHER_TYPES
from .run_contract import validate_run_contract


def _editorial_fallback_is_valid(brief: dict[str, Any]) -> bool:
    if str(brief.get("selection_mode") or "") != "editorial_calendar":
        return False
    evidence = brief.get("editorial_evidence") if isinstance(brief.get("editorial_evidence"), dict) else {}
    return bool(
        str(evidence.get("strategy_source") or "").strip()
        and str(evidence.get("calendar_column") or "").strip()
        and str(evidence.get("planned_for") or evidence.get("planned_date") or "").strip()
        and (evidence.get("dedupe_passed") is True or str(evidence.get("dedupe") or "").strip())
    )


def validate_pre_generation(job: dict[str, Any], brief: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    automated = brief.get("automated_workflow") is True
    production = os.environ.get("CONTENT_PLATFORM_RUNTIME_MODE", "").casefold() == "production"
    if not automated or not production:
        return {"version": "pre_generation_gate_v1", "passed": True, "skipped": True, "failures": []}

    platforms = [str(item).casefold() for item in job.get("platforms") or []]
    platform = platforms[0] if len(platforms) == 1 else ""
    failures: list[str] = []
    contract_gate = validate_run_contract(brief.get("run_contract"))
    failures.extend(contract_gate["failures"])

    matrix = brief.get("platform_source_matrix") if isinstance(brief.get("platform_source_matrix"), dict) else {}
    if not matrix:
        failures.append("platform_source_matrix.missing")
    elif str(matrix.get("platform") or "").casefold() != platform:
        failures.append("platform_source_matrix.platform_mismatch")
    elif not matrix.get("real_platform_collection_verified") and not _editorial_fallback_is_valid(brief):
        failures.append("platform_source_matrix.unverified")

    for field in ("content_blueprint", "content_profile", "capability_plan", "compiled_skill_rules", "bounded_model_input"):
        if not isinstance(brief.get(field), dict) or not brief[field]:
            failures.append(f"{field}.missing")

    required_media = required_artifact_kinds(platforms)
    media = config.get("media") if isinstance(config.get("media"), dict) else {}
    if required_media.intersection({"image", "cover"}) and not (media.get("image") or {}).get("enabled"):
        failures.append("image_provider.unavailable")
    if "video" in required_media:
        policy = config.get("content_policy") if isinstance(config.get("content_policy"), dict) else {}
        if not policy.get("allow_local_video_generation") or not (media.get("video") or {}).get("enabled"):
            failures.append("video_renderer.unavailable")

    expected_publisher = DELIVERY_PUBLISHER_TYPES.get(platform)
    routes = ((config.get("publishers") or {}).get("platforms") or {}) if isinstance(config.get("publishers"), dict) else {}
    route = routes.get(platform) if isinstance(routes.get(platform), dict) else {}
    if expected_publisher and str(route.get("type") or "") != expected_publisher:
        failures.append("publisher_route.unavailable_or_mismatch")

    return {
        "version": "pre_generation_gate_v1",
        "passed": not failures,
        "skipped": False,
        "platform": platform,
        "required_media": sorted(required_media),
        "failures": sorted(set(failures)),
    }
