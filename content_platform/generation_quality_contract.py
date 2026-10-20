"""Fail-closed quality contract for generated video content."""

from __future__ import annotations

from collections.abc import Mapping


class InvalidGenerationQualityContract(ValueError):
    """Raised when a video idea is not ready for asset or render work."""


_REQUIRED_FIELDS = (
    "audience",
    "repeated_task",
    "ai_intervention",
    "verifiable_result",
    "human_handoff",
    "viewer_promise",
    "hook",
    "evidence_ledger",
    "beats",
    "failure_boundary",
    "cta",
)

_EVIDENCE_STATUSES = {"measured", "pending_validation", "illustrative"}
_ASSET_ROLES = {"background", "evidence", "illustration"}


def validate_generation_quality_contract(
    contract: Mapping,
    *,
    beat_count_range: tuple[int, int] | None = None,
) -> dict:
    """Validate platform-neutral quality, then optional profile constraints."""
    if not isinstance(contract, Mapping):
        raise InvalidGenerationQualityContract("quality contract must be an object")
    for field in _REQUIRED_FIELDS:
        if field not in contract or contract[field] in (None, "", [], {}):
            raise InvalidGenerationQualityContract(f"missing required quality field: {field}")

    beats = contract["beats"]
    if not isinstance(beats, (list, tuple)) or not beats:
        raise InvalidGenerationQualityContract("quality contract requires at least one beat")
    beat_ids = [str(beat.get("beat_id") or "").strip() for beat in beats if isinstance(beat, Mapping)]
    if len(beat_ids) != len(beats) or any(not beat_id for beat_id in beat_ids) or len(set(beat_ids)) != len(beat_ids):
        raise InvalidGenerationQualityContract("quality contract requires a unique beat_id for every beat")
    if beat_count_range is not None:
        minimum, maximum = beat_count_range
        if minimum < 1 or maximum < minimum:
            raise InvalidGenerationQualityContract("invalid profile beat_count_range")
        if not minimum <= len(beats) <= maximum:
            raise InvalidGenerationQualityContract(
                f"profile requires {minimum}..{maximum} beats, got {len(beats)}"
            )
    for index, beat in enumerate(beats):
        if not isinstance(beat, Mapping):
            raise InvalidGenerationQualityContract(f"beats[{index}] must be an object")
        for field in ("content_job", "claim", "evidence", "viewer_result"):
            if not str(beat.get(field) or "").strip():
                raise InvalidGenerationQualityContract(
                    f"missing required quality field: beats[{index}].{field}"
                )

    hook = contract["hook"]
    if not isinstance(hook, Mapping):
        raise InvalidGenerationQualityContract("hook must be an object")
    for field in ("scene", "conflict", "consequence", "watch_reason"):
        if not str(hook.get(field) or "").strip():
            raise InvalidGenerationQualityContract(f"missing required quality field: hook.{field}")

    for index, entry in enumerate(contract["evidence_ledger"]):
        if not isinstance(entry, Mapping):
            raise InvalidGenerationQualityContract(f"evidence_ledger[{index}] must be an object")
        for field in ("claim", "status", "source"):
            if not str(entry.get(field) or "").strip():
                raise InvalidGenerationQualityContract(
                    f"missing required quality field: evidence_ledger[{index}].{field}"
                )
        if str(entry["status"]).strip() not in _EVIDENCE_STATUSES:
            raise InvalidGenerationQualityContract(
                f"evidence_ledger[{index}].status must be measured, pending_validation, or illustrative"
            )

    failure_boundary = contract["failure_boundary"]
    if not isinstance(failure_boundary, Mapping):
        raise InvalidGenerationQualityContract("failure_boundary must be an object")
    for field in ("trigger", "failure_mode", "verification_action", "authority_limit"):
        if not str(failure_boundary.get(field) or "").strip():
            raise InvalidGenerationQualityContract(
                f"missing required quality field: failure_boundary.{field}"
            )

    cta = contract["cta"]
    if not isinstance(cta, Mapping):
        raise InvalidGenerationQualityContract("cta must be an object")
    for field in ("audience_identity", "specific_question", "next_value"):
        if not str(cta.get(field) or "").strip():
            raise InvalidGenerationQualityContract(
                f"missing required quality field: cta.{field}"
            )

    return {"passed": True, "contract": dict(contract)}


def validate_asset_semantic_contract(asset_contract) -> dict:
    """Validate claim-to-asset intent without inventing VLM or provenance results."""
    if not isinstance(asset_contract, (list, tuple)) or not asset_contract:
        raise InvalidGenerationQualityContract("asset_semantic_contract must contain at least one beat")
    seen = set()
    for index, item in enumerate(asset_contract):
        if not isinstance(item, Mapping):
            raise InvalidGenerationQualityContract(f"asset_semantic_contract[{index}] must be an object")
        beat_id = str(item.get("beat_id") or "").strip()
        if not beat_id or beat_id in seen:
            raise InvalidGenerationQualityContract(f"asset_semantic_contract[{index}] requires unique beat_id")
        seen.add(beat_id)
        for field in ("claim", "asset_role", "semantic_subject", "content_match_reason", "verification_status"):
            if not str(item.get(field) or "").strip():
                raise InvalidGenerationQualityContract(f"missing required asset semantic field: [{index}].{field}")
        if str(item["asset_role"]).strip() not in _ASSET_ROLES:
            raise InvalidGenerationQualityContract(f"asset_semantic_contract[{index}].asset_role is invalid")
        if str(item["verification_status"]).strip() not in _EVIDENCE_STATUSES:
            raise InvalidGenerationQualityContract(f"asset_semantic_contract[{index}].verification_status is invalid")
    return {"passed": True, "asset_semantic_contract": list(asset_contract)}
