"""Fail-closed bridge from content evidence to a single video run contract."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .creative_structure_router import route_creative_structure
from .generation_quality_contract import (
    validate_asset_semantic_contract,
    validate_generation_quality_contract,
)
from .hot_viral_intelligence import build_hot_viral_intelligence
from .run_contract import validate_audio_plan
from .video_run import ArtifactRole, ArtifactSpec, RunManifest, RunSpec
from .video_platform_profile import (
    UnknownVideoPlatform,
    resolve_video_platform_profile,
)


class InvalidGenerationContract(ValueError):
    """Raised when production inputs cannot support an auditable video run."""


_REQUIRED_PLAN_FIELDS = (
    "platforms",
    "lane",
    "content_type",
    "evidence_shapes",
    "viewer_job",
    "hot_viral_samples",
    "visual_contract",
    "audio_plan",
)


def _require_plan_context(plan: Mapping) -> None:
    for field in _REQUIRED_PLAN_FIELDS:
        if field=="hot_viral_samples" and plan.get("content_mode")=="original_knowledge":
            if not plan.get("original_knowledge_ref"):
                raise InvalidGenerationContract("original native Store reference missing")
            continue
        if field not in plan or plan[field] in (None, "", [], {}):
            raise InvalidGenerationContract(f"missing required plan field: {field}")
    platforms = plan["platforms"]
    if not isinstance(platforms, list) or len(platforms) != 1 or not str(platforms[0]).strip():
        raise InvalidGenerationContract("platforms must contain exactly one target platform")


def _canonical_filename(value: object, field: str) -> str:
    filename = str(value or "").strip()
    path = Path(filename)
    if not filename or path.name != filename or any(char in filename for char in "*?[]") or path.suffix.casefold() != ".mp4":
        raise InvalidGenerationContract(f"{field} must be a plain .mp4 filename")
    return filename


def _attempt_identity(plan: Mapping) -> str:
    explicit = str(plan.get("attempt_id") or "").strip()
    raw_attempt = plan.get("attempt")
    derived = ""
    if raw_attempt not in (None, ""):
        try:
            attempt = int(raw_attempt)
        except (TypeError, ValueError) as exc:
            raise InvalidGenerationContract("attempt must be a positive integer") from exc
        if isinstance(raw_attempt, bool) or attempt < 1:
            raise InvalidGenerationContract("attempt must be a positive integer")
        derived = f"attempt-{attempt}"
    if explicit and derived and explicit != derived:
        raise InvalidGenerationContract(
            f"attempt identity conflict: attempt_id={explicit}, attempt={derived}"
        )
    return explicit or derived or "attempt-1"


def compile_generation_contract(
    plan: Mapping,
    *,
    output_dir: Path,
    input_paths: Mapping[str, Path],
) -> dict:
    """Compile auditable trend context, structure route, and immutable run identity."""
    _require_plan_context(plan)
    output_dir = Path(output_dir).resolve()
    canonical_name = _canonical_filename(plan.get("canonical_output_name"), "canonical_output_name")
    cover_name = str(plan.get("canonical_cover_name") or "cover.png").strip()
    cover_path = Path(cover_name)
    if not cover_name or cover_path.name != cover_name or cover_path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise InvalidGenerationContract("canonical_cover_name must be a plain image filename")

    platform = str(plan["platforms"][0]).strip()
    try:
        platform_profile = resolve_video_platform_profile(platform)
    except UnknownVideoPlatform as exc:
        raise InvalidGenerationContract(str(exc)) from exc
    audio_plan = dict(plan["audio_plan"])
    audio_validation = validate_audio_plan(audio_plan)
    if not audio_validation["passed"]:
        raise InvalidGenerationContract("invalid audio_plan: " + ", ".join(audio_validation["failures"]))
    if audio_plan.get("route") == "sfx_only":
        approved = audio_plan.get("no_bgm_approved") is True
        approval_source = str(audio_plan.get("approval_source") or "").strip()
        if not approved or approval_source != "explicit_user_request":
            raise InvalidGenerationContract(
                "sfx_only requires no_bgm_approved=true from explicit_user_request"
            )
    original=plan.get("content_mode")=="original_knowledge"
    if original:
        from .original_knowledge import original_intelligence
        try:
            intelligence=original_intelligence(plan)
        except (ValueError,OSError,KeyError) as exc:
            raise InvalidGenerationContract(str(exc)) from exc
    else:
        intelligence = build_hot_viral_intelligence(
        target_platform=platform,
        lane=str(plan["lane"]).strip(),
        samples=list(plan["hot_viral_samples"]),
        source_statuses=dict(plan.get("hot_viral_source_statuses") or {}),
    )
    if not original and intelligence.get("status") not in {"native_ready", "fallback_ready"}:
        # Explicit degradation is allowed only when the research layer proves
        # the limitation; it must never be presented as native heat or virality.
        context = intelligence.get("strategy_context") or {}
        degraded_ok = bool(
            plan.get("allow_degraded_render") is True
            and plan.get("allow_degraded_hot_intelligence") is True
            and plan.get("degraded_source") is True
            and str(plan.get("degradation_reason") or "").strip()
            and int(plan.get("research_source_count") or 0) >= 5
            and int(intelligence.get("topic_signal_count") or 0) > 0
            and str(context.get("mode") or "") not in {"", "unavailable"}
        )
        if degraded_ok:
            intelligence = {
                **intelligence,
                "status": "degraded_candidate",
                "native_ready": False,
                "native_verified": False,
                "evidence_grade": "C_explicit_degradation",
                "blocking_reasons": list(intelligence.get("blocking_reasons") or [])
                + ["target_platform_native_metrics_unavailable"],
                "degradation_reason": str(plan["degradation_reason"]).strip(),
                "claims_forbidden": [
                    "target-platform native ranking",
                    "viral guarantee",
                    "unverified engagement metrics",
                ],
            }
        else:
            reasons = ", ".join(intelligence.get("blocking_reasons") or ["insufficient hot/viral evidence"])
            raise InvalidGenerationContract(f"hot_viral_samples blocked: {reasons}")

    creative = route_creative_structure(
        content_type=str(plan["content_type"]).strip(),
        evidence_shapes=[str(item).strip() for item in plan["evidence_shapes"]],
        platform=platform,
        viewer_job=str(plan["viewer_job"]).strip(),
        recent_fingerprints=tuple(plan.get("recent_structure_fingerprints") or ()),
        history_window=int(plan.get("structure_history_window") or 5),
        external_candidates=tuple(plan.get("external_structure_candidates") or ()),
    )
    generation_quality = None
    asset_semantics = None
    if plan.get("generation_quality_contract") is not None:
        generation_quality = validate_generation_quality_contract(
            plan["generation_quality_contract"],
            beat_count_range=platform_profile.beat_count_range,
        )
    if plan.get("asset_semantic_contract") is not None:
        asset_semantics = validate_asset_semantic_contract(plan["asset_semantic_contract"])

    artifacts = [
        ArtifactSpec(name=str(name), path=Path(path), role=ArtifactRole.INPUT)
        for name, path in sorted(input_paths.items())
    ]
    artifacts.extend(
        (
            ArtifactSpec(name="video", path=output_dir / canonical_name, role=ArtifactRole.OUTPUT),
            ArtifactSpec(name="cover", path=output_dir / cover_name, role=ArtifactRole.OUTPUT),
        )
    )
    spec = RunSpec(
        run_id=str(plan.get("run_id") or "").strip(),
        revision=int(plan.get("revision") or 0),
        artifacts=tuple(artifacts),
        attempt_id=_attempt_identity(plan),
    )
    manifest = RunManifest.plan(spec)
    contract = {
        "version": "video_generation_contract_v1",
        "target_platform": platform,
        "platform_profile": {
            "id": platform_profile.id,
            "format_profile": platform_profile.format_profile,
            "language": platform_profile.language,
            "aspect_ratio": platform_profile.aspect_ratio,
            "width": platform_profile.width,
            "height": platform_profile.height,
            "beat_count_range": list(platform_profile.beat_count_range),
            "lane": platform_profile.lane,
        },
        "hot_viral_intelligence": {} if original else intelligence,
        "creative_structure": creative,
        "audio_plan": audio_plan,
        "canonical_output": str((output_dir / canonical_name).resolve()),
        "canonical_cover": str((output_dir / cover_name).resolve()),
        "run_manifest": manifest,
    }
    if generation_quality is not None:
        contract["generation_quality"] = generation_quality
    if asset_semantics is not None:
        contract["asset_semantic_contract"] = asset_semantics
    if original:
        contract["original_knowledge_intelligence"]=intelligence
    return contract
