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


def test_generate_payload_compacts_optional_context_but_preserves_core_fields(tmp_path: Path) -> None:
    rulebook = tmp_path / "rulebook.json"
    rulebook.write_text(json.dumps({"version": "test", "channel_rules": {"demo": {}}}), encoding="utf-8")
    contract = build_run_contract("demo", rulebook_path=rulebook)
    payload = {
        "content_blueprint": {"topic": "core topic", "steps": ["step-1", "step-2"]},
        "content_profile": {"domain": "tech", "format": "short_video"},
        "capability_plan": {"required": ["tts", "renderer"]},
        "tool_selection": {"selected": ["edge_tts", "ffmpeg"]},
        "compiled_skill_rules": {"rules": ["rule-" + ("x" * 500) for _ in range(20)]},
        "tool_selection_plan": {"candidates": ["tool-" + ("x" * 500) for _ in range(20)]},
        "strategy": {"platform": "demo"},
        "content_quality_reference_pack": {"sections": ["ref-" + ("x" * 500) for _ in range(20)]},
        "runtime_capabilities": {"tools": {"tool": {"notes": "x" * 5000}}},
        "same_lane_intelligence": {"patterns": ["pattern-" + ("x" * 500) for _ in range(20)]},
        "hot_work_parameter_pack": {"samples": ["sample-" + ("x" * 500) for _ in range(20)]},
    }
    bounded = bound_stage_payload(contract, "generate", payload, rulebook_path=rulebook)
    assert bounded["content_blueprint"]["topic"] == "core topic"
    assert bounded["content_profile"]["domain"] == "tech"
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= contract["bounds"]["stage_payload_bytes"]
