"""Compile the effective per-platform rules into a bounded runtime contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .preflight_manifest import REQUIRED_SKILLS_BY_CHANNEL


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULEBOOK = ROOT / "config" / "channel_content_rulebook.json"
MANUAL_PLATFORMS = {
    "bilibili", "douyin", "douyin_ai", "douyin_pet", "shipinhao",
    "xiaohongshu", "youtube", "tiktok",
}
PLATFORM_ALIASES = {"douyin_pet": "douyin", "twitter": "twitter"}
PRECEDENCE = [
    "global_hard_gates",
    "platform_publish_boundary",
    "current_run_approval_state",
    "channel_rules",
    "validated_runtime_configuration",
    "legacy_compatibility_defaults",
]
STAGE_FIELDS = {
    "collect": {"platform", "source_report", "strategy_status"},
    "select": {"candidates", "reserved_topics", "lane_keywords", "editorial_fallback"},
    "blueprint": {"selected_topic", "platform_source_matrix", "account_context", "strategy"},
    "generate": {"content_blueprint", "claim_ledger", "tool_selection_plan", "audio_plan", "strategy", "positioning", "platform_intelligence_constraints", "external_discovery_candidates", "content_quality_reference_pack", "runtime_capabilities", "distilled_per_account", "hot_work_parameter_pack", "same_lane_intelligence", "viral_breakdown", "wechat_blowup_intelligence", "owned_learning_decision", "owned_learning_treatment"},
    "assets": {"scene_manifest", "asset_requirements", "claim_ledger", "cover_brief"},
    "render": {"scene_manifest", "voice_plan", "bgm_plan", "audio_plan", "cover_brief"},
    "deliver": {"artifacts", "gate_results", "publish_info"},
}
BOUNDS = {
    "stage_payload_bytes": 16_384,
    "provider_response_bytes": 1_048_576,
    "source_rows": 64,
    "video_segments": 8,
    "image_prompt_chars": 1_200,
}


class RunContractError(ValueError):
    pass


AUDIO_ROUTES = {
    "platform_native_track",
    "embedded_licensed_bgm",
    "preserve_source_audio",
    "sfx_only",
}

AUDIO_ROUTE_REQUIRED_FIELDS = {
    "platform_native_track": ("platform", "track_id", "track_url", "trend_evidence", "rights_scope", "apply_stage"),
    "embedded_licensed_bgm": ("license", "source_url", "fingerprint", "rights_scope"),
    "preserve_source_audio": ("source_audio_rights", "source_audio_fingerprint"),
    "sfx_only": ("no_bgm_approved", "approval_source"),
}


def validate_audio_plan(
    audio_plan: dict[str, Any] | None, *, require_bgm: bool = False
) -> dict[str, Any]:
    """Validate an explicit audio route without guessing missing rights evidence."""
    if not isinstance(audio_plan, dict):
        return {"passed": False, "failures": ["audio_plan.missing"]}
    failures: list[str] = []
    route = str(audio_plan.get("route") or "").strip()
    if route not in AUDIO_ROUTES:
        failures.append("audio_plan.route_invalid")
    for field in ("route_reason", "source_audio_action"):
        if audio_plan.get(field) in (None, "", [], {}):
            failures.append(f"audio_plan.{field}_missing")
    if "fallback_route" not in audio_plan:
        failures.append("audio_plan.fallback_route_missing")
    else:
        fallback = audio_plan.get("fallback_route")
        if fallback not in (None, "") and fallback not in AUDIO_ROUTES:
            failures.append("audio_plan.fallback_route_invalid")
    for field in AUDIO_ROUTE_REQUIRED_FIELDS.get(route, ()):
        if audio_plan.get(field) in (None, "", [], {}):
            failures.append(f"audio_plan.{field}_missing")
    if route == "sfx_only":
        if audio_plan.get("no_bgm_approved") is not True:
            failures.append("audio_plan.no_bgm_approved_invalid")
        if audio_plan.get("approval_source") != "explicit_user_request":
            failures.append("audio_plan.approval_source_invalid")
        if require_bgm:
            failures.append("audio_plan.sfx_only_conflicts_with_bgm_requirement")
    return {"passed": not failures, "failures": failures}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RunContractError("rulebook must be a JSON object")
    return value


def build_run_contract(
    platform: str,
    *,
    rulebook_path: str | Path = DEFAULT_RULEBOOK,
    audio_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(platform or "").casefold().strip()
    if not normalized:
        raise RunContractError("platform is required")
    path = Path(rulebook_path).resolve()
    rulebook = _load(path)
    channel_key = PLATFORM_ALIASES.get(normalized, normalized)
    channel_rules = (rulebook.get("channel_rules") or {}).get(channel_key) or {
        "status": "unsupported_pre_onboarding",
        "publish_policy": "blocked_without_explicit_channel_onboarding",
        "quality_gates": [],
    }
    effective_audio_plan = dict(audio_plan) if isinstance(audio_plan, dict) else None
    if effective_audio_plan is not None:
        audio_validation = validate_audio_plan(effective_audio_plan)
        if not audio_validation["passed"]:
            raise RunContractError("invalid audio_plan: " + ",".join(audio_validation["failures"]))
    skills = sorted(REQUIRED_SKILLS_BY_CHANNEL.get(normalized) or REQUIRED_SKILLS_BY_CHANNEL.get(channel_key) or {"meta/content-preflight", "content/content-strategy-workflow"})
    return {
        "version": "run_contract_v1",
        "platform": normalized,
        "channel_key": channel_key,
        "rulebook": {
            "path": "config/channel_content_rulebook.json",
            "version": str(rulebook.get("version") or ""),
            "sha256": _sha256(path),
        },
        "precedence": list(PRECEDENCE),
        "publish_boundary": (
            "manual_handoff_only"
            if normalized in MANUAL_PLATFORMS
            else "unsupported_pre_onboarding"
            if channel_rules.get("status") == "unsupported_pre_onboarding"
            else "policy_controlled_publish"
        ),
        "strategy_evidence_required": True,
        "enforce_strategy_evidence": True,
        "keyword_tool_execution_required": True,
        "mandatory_sequence": list(rulebook.get("mandatory_sequence") or []),
        "global_hard_gates": dict(rulebook.get("global_hard_gates") or {}),
        "visual_quality_standards": dict(rulebook.get("visual_quality_standards") or {}),
        "channel_rules": channel_rules,
        "required_skills": skills,
        "stage_fields": {stage: sorted(fields) for stage, fields in STAGE_FIELDS.items()},
        "bounds": dict(BOUNDS),
        **({"audio_plan": effective_audio_plan} if effective_audio_plan is not None else {}),
    }


def validate_run_contract(contract: dict[str, Any] | None, *, rulebook_path: str | Path = DEFAULT_RULEBOOK) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(contract, dict):
        return {"passed": False, "failures": ["run_contract.missing"]}
    if contract.get("version") != "run_contract_v1":
        failures.append("run_contract.version_mismatch")
    path = Path(rulebook_path).resolve()
    rulebook_meta = contract.get("rulebook") or {}
    if not path.is_file():
        failures.append("run_contract.rulebook_missing")
    elif str(rulebook_meta.get("sha256") or "") != _sha256(path):
        failures.append("run_contract.rulebook_sha256_mismatch")
    current = _load(path) if path.is_file() else {}
    if str(rulebook_meta.get("version") or "") != str(current.get("version") or ""):
        failures.append("run_contract.rulebook_version_mismatch")
    if contract.get("visual_quality_standards") != dict(current.get("visual_quality_standards") or {}):
        failures.append("run_contract.visual_quality_standards_mismatch")
    if contract.get("strategy_evidence_required") is not True or contract.get("enforce_strategy_evidence") is not True:
        failures.append("run_contract.strategy_evidence_enforcement_required")
    if contract.get("precedence") != PRECEDENCE:
        failures.append("run_contract.precedence_mismatch")
    if "audio_plan" in contract:
        audio_validation = validate_audio_plan(contract.get("audio_plan"))
        failures.extend(f"run_contract.{failure}" for failure in audio_validation["failures"])
    platform = str(contract.get("platform") or "").casefold()
    channel_rules = contract.get("channel_rules") or {}
    expected_boundary = (
        "manual_handoff_only"
        if platform in MANUAL_PLATFORMS
        else "unsupported_pre_onboarding"
        if channel_rules.get("status") == "unsupported_pre_onboarding"
        else "policy_controlled_publish"
    )
    if contract.get("publish_boundary") != expected_boundary:
        failures.append("run_contract.publish_boundary_mismatch")
    if not contract.get("required_skills") or not contract.get("stage_fields") or not contract.get("bounds"):
        failures.append("run_contract.incomplete")
    return {"passed": not failures, "failures": failures}


def bound_stage_payload(
    contract: dict[str, Any],
    stage: str,
    payload: dict[str, Any],
    *,
    rulebook_path: str | Path = DEFAULT_RULEBOOK,
) -> dict[str, Any]:
    validation = validate_run_contract(contract, rulebook_path=rulebook_path)
    if not validation["passed"]:
        raise RunContractError("invalid run contract: " + ",".join(validation["failures"]))
    allowed = set((contract.get("stage_fields") or {}).get(stage) or [])
    if not allowed:
        raise RunContractError(f"unknown stage: {stage}")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise RunContractError("unknown stage fields: " + ",".join(unknown))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    limit = int((contract.get("bounds") or {}).get("stage_payload_bytes") or BOUNDS["stage_payload_bytes"])
    if len(encoded) > limit:
        raise RunContractError(f"payload exceeds {limit} bytes")
    return json.loads(encoded.decode("utf-8"))
