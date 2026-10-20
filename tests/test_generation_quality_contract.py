from __future__ import annotations

import pytest


def _quality_contract() -> dict:
    return {
        "audience": "设备运维工程师",
        "repeated_task": "判断电机是否需要停机检查",
        "ai_intervention": "分析振动、温度和电流趋势并生成检查清单",
        "verifiable_result": "异常设备、异常时段和建议检查部位",
        "human_handoff": "工程师结合巡检记录和现场状态决定是否停机或换件",
        "viewer_promise": "看完能理解异常趋势如何变成检查工单，并知道一次报警不能直接决定停机",
        "hook": {
            "scene": "电机仍在正常运转",
            "conflict": "AI却提前把轴承标红",
            "consequence": "等到出现异响可能只能停机处理",
            "watch_reason": "接下来展示异常趋势如何变成可复核的检查工单",
        },
        "evidence_ledger": [
            {
                "claim": "异常趋势会先进入人工复核",
                "status": "measured",
                "source": "巡检记录与检查工单",
            }
        ],
        "beats": [
            {
                "beat_id": f"s{index:02d}",
                "content_job": f"推进运维判断步骤 {index}",
                "claim": f"本段主张 {index}",
                "evidence": f"本段证据 {index}",
                "viewer_result": f"观众获得的判断 {index}",
            }
            for index in range(1, 9)
        ],
        "failure_boundary": {
            "trigger": "负载突变、传感器松动或维修后基线未更新",
            "failure_mode": "可能出现误报",
            "verification_action": "工程师核对负载、传感器和巡检记录",
            "authority_limit": "AI不能单凭一次报警决定停机或换件",
        },
        "cta": {
            "audience_identity": "设备运维或生产管理人员",
            "specific_question": "你们现场最难判断的是轴承、泵还是空压机？",
            "next_value": "按最高票场景拆下一条检查流程",
        },
    }


def test_quality_contract_rejects_missing_human_handoff() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["human_handoff"] = ""

    with pytest.raises(InvalidGenerationQualityContract, match="human_handoff"):
        validate_generation_quality_contract(contract)


def test_quality_contract_requires_unique_beats_but_not_a_core_fixed_count() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["beats"][-1]["beat_id"] = "s07"

    with pytest.raises(InvalidGenerationQualityContract, match="unique beat_id"):
        validate_generation_quality_contract(contract)

    long_form = _quality_contract()
    long_form["beats"].extend(
        {
            "beat_id": f"s{index:02d}",
            "content_job": f"推进长视频论证步骤 {index}",
            "claim": f"长视频主张 {index}",
            "evidence": f"长视频证据 {index}",
            "viewer_result": f"长视频观众结果 {index}",
        }
        for index in range(9, 13)
    )

    assert validate_generation_quality_contract(long_form)["passed"] is True


def test_quality_contract_applies_profile_beat_count_range() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["beats"].pop()

    with pytest.raises(InvalidGenerationQualityContract, match="profile requires 8..8 beats"):
        validate_generation_quality_contract(contract, beat_count_range=(8, 8))


def test_quality_contract_rejects_hook_without_real_scene_conflict_consequence_or_watch_reason() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["hook"]["consequence"] = ""

    with pytest.raises(InvalidGenerationQualityContract, match="hook.consequence"):
        validate_generation_quality_contract(contract)


def test_quality_contract_rejects_beat_without_claim_evidence_or_viewer_result() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["beats"][3]["evidence"] = ""

    with pytest.raises(InvalidGenerationQualityContract, match=r"beats\[3\]\.evidence"):
        validate_generation_quality_contract(contract)


def test_quality_contract_rejects_unknown_evidence_status() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["evidence_ledger"][0]["status"] = "proven_by_ai"

    with pytest.raises(InvalidGenerationQualityContract, match=r"evidence_ledger\[0\]\.status"):
        validate_generation_quality_contract(contract)


def test_quality_contract_rejects_incomplete_failure_boundary() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["failure_boundary"]["authority_limit"] = ""

    with pytest.raises(InvalidGenerationQualityContract, match="failure_boundary.authority_limit"):
        validate_generation_quality_contract(contract)


def test_quality_contract_rejects_generic_cta_without_specific_question_or_next_value() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_generation_quality_contract,
    )

    contract = _quality_contract()
    contract["cta"]["specific_question"] = ""

    with pytest.raises(InvalidGenerationQualityContract, match="cta.specific_question"):
        validate_generation_quality_contract(contract)


def test_asset_semantic_contract_requires_claim_role_subject_reason_and_status() -> None:
    from content_platform.generation_quality_contract import (
        InvalidGenerationQualityContract,
        validate_asset_semantic_contract,
    )

    with pytest.raises(InvalidGenerationQualityContract, match="semantic_subject"):
        validate_asset_semantic_contract([{
            "beat_id": "s01", "claim": "设备出现异常趋势", "asset_role": "background",
            "content_match_reason": "工业现场对应设备运转", "verification_status": "pending_validation",
        }])

    result = validate_asset_semantic_contract([{
        "beat_id": "s01", "claim": "设备出现异常趋势", "asset_role": "background",
        "semantic_subject": "运行中的电机与传感器", "content_match_reason": "工业现场对应设备运转",
        "verification_status": "pending_validation",
    }])
    assert result["passed"] is True
