"""Compile the effective per-platform rules into a bounded runtime contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .content_policy import delivery_mode
from .preflight_manifest import REQUIRED_SKILLS_BY_CHANNEL


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULEBOOK = ROOT / "config" / "channel_content_rulebook.json"
PLATFORM_ALIASES = {"douyin_ai": "douyin", "douyin_pet": "douyin", "twitter": "twitter"}
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
    "generate": {"content_blueprint", "content_profile", "capability_plan", "tool_selection", "compiled_skill_rules", "associated_hotspot", "claim_ledger", "tool_selection_plan", "strategy", "content_quality_reference_pack", "runtime_capabilities", "distilled_per_account", "hot_work_parameter_pack", "same_lane_intelligence"},
    "assets": {"scene_manifest", "asset_requirements", "claim_ledger", "cover_brief"},
    "render": {"scene_manifest", "voice_plan", "bgm_plan", "cover_brief"},
    "deliver": {"artifacts", "gate_results", "publish_info"},
}
BOUNDS = {
    "stage_payload_bytes": 16_384,
    "provider_response_bytes": 1_048_576,
    "source_rows": 64,
    "video_segments": 8,
    "image_prompt_chars": 1_200,
    "generation_soft_deadline_seconds": 90,
    "generation_hard_deadline_seconds": 180,
    "generation_heartbeat_seconds": 15,
    "generation_max_attempts": 2,
}


class RunContractError(ValueError):
    pass


def _publish_boundary(platform: str) -> str:
    mode = delivery_mode(platform)
    if mode == "manual_handoff":
        return "manual_handoff_only"
    if mode == "unsupported":
        return "unsupported_pre_onboarding"
    return "policy_controlled_publish"


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


def build_run_contract(platform: str, *, rulebook_path: str | Path = DEFAULT_RULEBOOK) -> dict[str, Any]:
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
        "delivery_mode": delivery_mode(normalized),
        "publish_boundary": _publish_boundary(normalized),
        "mandatory_sequence": list(rulebook.get("mandatory_sequence") or []),
        "global_hard_gates": dict(rulebook.get("global_hard_gates") or {}),
        "channel_rules": channel_rules,
        "required_skills": skills,
        "stage_fields": {stage: sorted(fields) for stage, fields in STAGE_FIELDS.items()},
        "bounds": dict(BOUNDS),
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
    if contract.get("precedence") != PRECEDENCE:
        failures.append("run_contract.precedence_mismatch")
    platform = str(contract.get("platform") or "").casefold()
    expected_mode = delivery_mode(platform)
    if contract.get("delivery_mode") != expected_mode:
        failures.append("run_contract.delivery_mode_mismatch")
    expected_boundary = _publish_boundary(platform)
    if contract.get("publish_boundary") != expected_boundary:
        failures.append("run_contract.publish_boundary_mismatch")
    if not contract.get("required_skills") or not contract.get("stage_fields") or not contract.get("bounds"):
        failures.append("run_contract.incomplete")
    return {"passed": not failures, "failures": failures}


_GENERATION_OPTIONAL_FIELDS = (
    "compiled_skill_rules",
    "content_profile",
    "capability_plan",
    "tool_selection",
    "tool_selection_plan",
    "content_quality_reference_pack",
    "runtime_capabilities",
    "distilled_per_account",
    "hot_work_parameter_pack",
    "same_lane_intelligence",
)
_SAME_LANE_GUARD_FIELDS = (
    "strategy_claim_boundary",
    "generation_rules",
    "evidence_quality",
    "source",
    "source_type",
    "source_label",
    "source_labels",
    "evidence",
    "evidence_type",
    "evidence_label",
    "evidence_labels",
    "provenance_kind",
)


def _compact_json_value(value: Any, *, max_items: int, max_string: int, depth: int = 0) -> Any:
    """Bound verbose advisory context without dropping core generation fields."""
    if isinstance(value, str):
        return value[:max_string]
    if isinstance(value, list):
        return [
            _compact_json_value(item, max_items=max_items, max_string=max_string, depth=depth + 1)
            for item in value[:max_items]
        ]
    if isinstance(value, dict):
        items = list(value.items())
        if depth >= 5:
            return {str(key): str(item)[:max_string] for key, item in items[:max_items]}
        return {
            str(key): _compact_json_value(item, max_items=max_items, max_string=max_string, depth=depth + 1)
            for key, item in items[: max_items * 2]
        }
    return value


def _compact_generation_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    """Shrink only optional advisory fields when real strategy context is large."""
    candidate = dict(payload)
    for max_items, max_string in ((6, 240), (3, 160), (2, 100)):
        for field in _GENERATION_OPTIONAL_FIELDS:
            if field in candidate:
                if field == "same_lane_intelligence" and isinstance(candidate[field], dict):
                    candidate[field] = {
                        key: _compact_json_value(candidate[field][key], max_items=max_items, max_string=max_string)
                        for key in (
                            "version", "platform", "own_data_status", "topic_patterns",
                            "proof_requirements", "recommended_content_moves", "top_accounts", "top_works",
                            *_SAME_LANE_GUARD_FIELDS,
                        )
                        if key in candidate[field]
                    }
                else:
                    candidate[field] = _compact_json_value(
                        candidate[field], max_items=max_items, max_string=max_string
                    )
        if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= limit:
            return candidate
    return candidate


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
    if stage == "generate" and len(encoded) > limit:
        payload = _compact_generation_payload(payload, limit)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > limit:
        raise RunContractError(f"payload exceeds {limit} bytes")
    return json.loads(encoded.decode("utf-8"))
