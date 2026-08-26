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
    assert contract["delivery_mode"] == "manual_handoff"
    assert contract["precedence"][0] == "global_hard_gates"
    assert validate_run_contract(contract, rulebook_path=_rulebook(tmp_path))["passed"] is True


def test_run_contract_fails_closed_for_unknown_platform_even_if_rulebook_lists_it(tmp_path: Path) -> None:
    rulebook = _rulebook(tmp_path)
    payload = json.loads(rulebook.read_text(encoding="utf-8"))
    payload["channel_rules"]["future_channel"] = {"publish_policy": "automatic", "quality_gates": []}
    rulebook.write_text(json.dumps(payload), encoding="utf-8")

    contract = build_run_contract("future_channel", rulebook_path=rulebook)

    assert contract["delivery_mode"] == "unsupported"
    assert contract["publish_boundary"] == "unsupported_pre_onboarding"
    assert validate_run_contract(contract, rulebook_path=rulebook)["passed"] is True


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


def test_generate_payload_compacts_server_scale_capability_context(tmp_path: Path) -> None:
    rulebook = _rulebook(tmp_path)
    contract = build_run_contract("tiktok", rulebook_path=rulebook)
    verbose = {f"capability_{index}": {"rules": ["中文规则" * 80] * 8} for index in range(80)}

    bounded = bound_stage_payload(
        contract,
        "generate",
        {
            "content_blueprint": {"topic": "AI workflow", "content_form": "short_video"},
            "claim_ledger": [{"claim": "verified claim", "source": "evidence"}],
            "strategy": {"account_identity": "tiktok-ai"},
            "content_profile": verbose,
            "capability_plan": verbose,
            "tool_selection": verbose,
            "compiled_skill_rules": verbose,
            "same_lane_intelligence": {
                "version": "same_lane_playbook_compact_v1",
                "own_data_status": "insufficient",
                "strategy_claim_boundary": "competitor_inspired_not_auto_tuned",
                "generation_rules": [
                    "如果自有指标不足，必须标注为竞品启发，不得写成自有数据结论",
                    "不得把跨平台样本改标为本平台原生证据",
                ],
                "source_label": "same_lane_competitor_sample",
                "evidence_label": "platform_native_work",
                "topic_patterns": ["tool_workflow_tutorial"],
                "proof_requirements": ["screen_or_tool_stack_demo"],
                "recommended_content_moves": ["show a concrete tool stack"],
                "verbose_rows": verbose,
            },
        },
        rulebook_path=rulebook,
    )

    assert bounded["content_blueprint"]["topic"] == "AI workflow"
    assert bounded["claim_ledger"][0]["claim"] == "verified claim"
    assert bounded["strategy"]["account_identity"] == "tiktok-ai"
    assert bounded["same_lane_intelligence"]["strategy_claim_boundary"] == "competitor_inspired_not_auto_tuned"
    assert "竞品启发" in bounded["same_lane_intelligence"]["generation_rules"][0]
    assert bounded["same_lane_intelligence"]["source_label"] == "same_lane_competitor_sample"
    assert bounded["same_lane_intelligence"]["evidence_label"] == "platform_native_work"
    assert bounded["same_lane_intelligence"]["topic_patterns"] == ["tool_workflow_tutorial"]
    assert len(json.dumps(bounded, ensure_ascii=False).encode("utf-8")) <= 16_384
