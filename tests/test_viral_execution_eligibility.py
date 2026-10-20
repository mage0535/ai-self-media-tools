import pytest

from content_platform.viral_execution import build_viral_execution_policy


def _report():
    return {
        "status": "ready",
        "validation": {"passed": True},
        "summary": {"accepted_samples": 1},
        "samples": [{
            "copy_or_script": "用现场证据解释问题",
            "content_structure": ["问题", "证据", "结果"],
            "writing_style": "短句",
            "content_form": "case_study",
            "topic_direction": "真实场景",
            "asset_analysis": {"count": 1},
            "theme_template": {"template_id": "evidence"},
            "motion_combination": {"status": "verified"},
            "transition_combination": {"status": "verified"},
            "voiceover": {"status": "verified"},
            "visual_evidence": ["frame-manifest"],
            "reference_ids": ["work-1"],
        }],
    }


def test_execution_policy_requires_evaluator_issued_advice_permission():
    with pytest.raises(ValueError, match="advice_not_eligible"):
        build_viral_execution_policy(_report())

    policy = build_viral_execution_policy(_report(), eligibility={
        "state": "S5_ADVISE",
        "permissions": {"allow_advice": True},
        "platform": "youtube",
        "lane": "real_world_ai_implementation",
    })
    assert policy["eligibility_state"] == "S5_ADVISE"
