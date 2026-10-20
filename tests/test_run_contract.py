from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_platform.run_contract import (
    RunContractError,
    build_run_contract,
    bound_stage_payload,
    validate_run_contract,
)


def _rulebook(tmp_path: Path) -> Path:
    path = tmp_path / "channel_content_rulebook.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "mandatory_sequence": ["collect", "generate", "gate"],
                "global_hard_gates": {"no_secret_output": True},
                "channel_rules": {
                    "tiktok": {
                        "quality_gates": ["video", "cover"],
                        "publish_policy": "manual_only",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_contract_records_rule_hash_precedence_and_manual_boundary(tmp_path: Path) -> None:
    contract = build_run_contract("tiktok", rulebook_path=_rulebook(tmp_path))

    assert contract["rulebook"]["version"] == "test-v1"
    assert len(contract["rulebook"]["sha256"]) == 64
    assert contract["publish_boundary"] == "manual_handoff_only"
    assert contract["precedence"][0] == "global_hard_gates"
    assert validate_run_contract(contract, rulebook_path=_rulebook(tmp_path))["passed"] is True


def test_run_contract_detects_rulebook_drift(tmp_path: Path) -> None:
    rulebook = _rulebook(tmp_path)
    contract = build_run_contract("tiktok", rulebook_path=rulebook)
    payload = json.loads(rulebook.read_text(encoding="utf-8"))
    payload["global_hard_gates"]["new_gate"] = True
    rulebook.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_run_contract(contract, rulebook_path=rulebook)

    assert result["passed"] is False
    assert "run_contract.rulebook_sha256_mismatch" in result["failures"]


def test_stage_payload_is_bounded_and_rejects_unknown_fields(tmp_path: Path) -> None:
    rulebook = _rulebook(tmp_path)
    contract = build_run_contract("tiktok", rulebook_path=rulebook)
    bounded = bound_stage_payload(
        contract,
        "blueprint",
        {
            "selected_topic": "meeting notes",
            "platform_source_matrix": {"sources": []},
            "account_context": {"lane": "AI"},
        },
        rulebook_path=rulebook,
    )
    assert bounded["selected_topic"] == "meeting notes"
    with pytest.raises(RunContractError, match="unknown stage fields"):
        bound_stage_payload(contract, "blueprint", {"selected_topic": "x", "shell_command": "rm"}, rulebook_path=rulebook)


def test_stage_payload_rejects_oversized_provider_input(tmp_path: Path) -> None:
    rulebook = _rulebook(tmp_path)
    contract = build_run_contract("tiktok", rulebook_path=rulebook)
    with pytest.raises(RunContractError, match="payload exceeds"):
        bound_stage_payload(contract, "blueprint", {"selected_topic": "x" * 20_000}, rulebook_path=rulebook)


def test_run_contract_does_not_invent_sfx_only_when_audio_plan_is_missing(tmp_path: Path) -> None:
    contract = build_run_contract("tiktok", rulebook_path=_rulebook(tmp_path))

    assert "audio_plan" in contract["stage_fields"]["generate"]
    assert "audio_plan" in contract["stage_fields"]["render"]
    assert "audio_plan" not in contract


def test_sfx_only_requires_explicit_user_no_bgm_approval() -> None:
    from content_platform.run_contract import validate_audio_plan

    base = {
        "route": "sfx_only",
        "route_reason": "the user explicitly requested no music",
        "source_audio_action": "replace_with_voiceover_and_sfx",
        "fallback_route": None,
    }
    assert validate_audio_plan(base)["passed"] is False
    assert validate_audio_plan({**base, "no_bgm_approved": True})["passed"] is False
    assert validate_audio_plan({**base, "no_bgm_approved": True, "approval_source": "ai_workflow_default"})["passed"] is False
    assert validate_audio_plan({**base, "no_bgm_approved": True, "approval_source": "explicit_user_request"})["passed"] is True


def test_sfx_only_is_rejected_when_the_work_requires_background_music() -> None:
    from content_platform.run_contract import validate_audio_plan

    result = validate_audio_plan(
        {
            "route": "sfx_only",
            "route_reason": "the user explicitly requested no music",
            "source_audio_action": "replace_with_voiceover_and_sfx",
            "fallback_route": None,
            "no_bgm_approved": True,
            "approval_source": "explicit_user_request",
        },
        require_bgm=True,
    )

    assert result["passed"] is False
    assert "audio_plan.sfx_only_conflicts_with_bgm_requirement" in result["failures"]


def test_validate_audio_plan_requires_native_track_evidence() -> None:
    from content_platform.run_contract import validate_audio_plan

    result = validate_audio_plan(
        {
            "route": "platform_native_track",
            "route_reason": "use the current native trend",
            "source_audio_action": "replace",
            "fallback_route": None,
            "platform": "tiktok",
            "track_id": "track-123",
            "track_url": "https://www.tiktok.com/music/track-123",
            "trend_evidence": {"observed_at": "2026-09-16T09:00:00Z", "rank": 4},
            "rights_scope": "tiktok_native_use",
            "apply_stage": "platform_publish",
        }
    )
    assert result["passed"] is True

    missing = validate_audio_plan({"route": "platform_native_track", "route_reason": "trend", "source_audio_action": "replace", "fallback_route": None})
    assert missing["passed"] is False
    assert "audio_plan.track_id_missing" in missing["failures"]
