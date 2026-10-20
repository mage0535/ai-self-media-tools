import pytest

from content_platform.viral_execution import build_viral_execution_policy, find_viral_report


def report(**sample_overrides):
    sample = {
        "title": "参考样本",
        "content_form": "failure_recovery",
        "copy_or_script": "先展示错误，再现场修复，最后给边界",
        "writing_style": "第一人称、短句、带停顿",
        "content_structure": ["失败", "定位", "修复", "边界"],
        "topic_direction": "真实排障",
        "asset_analysis": {"type": "terminal", "count": 1},
        "theme_template": {"template_id": "terminal_evidence"},
        "motion_combination": {"status": "verified", "moves": ["local_highlight", "type_in"]},
        "transition_combination": {"status": "verified", "semantics": ["evidence_shock", "state_change"]},
        "voiceover": {"status": "verified", "style": "calm_testimony"},
        "visual_evidence": ["/tmp/reference.mp4"],
        "selected_hook": "这条错误日志，暴露了真正的根因",
        "narrative_engine": "失败复盘",
        "evidence_sequence": ["错误", "日志", "修复结果"],
        "reference_ids": ["ref-001"],
    }
    sample.update(sample_overrides)
    return {
        "version": "viral_breakdown_v2",
        "status": "ready",
        "validation": {"passed": True},
        "summary": {"accepted_samples": 1},
        "samples": [sample],
    }


def eligibility():
    return {
        "state": "S5_ADVISE",
        "permissions": {"allow_advice": True},
        "platform": "kuaishou",
        "lane": "real_world_ai_implementation",
    }


def test_policy_contains_executable_fields_and_stable_hash():
    policy = build_viral_execution_policy(report(), eligibility=eligibility())
    assert policy["selected_hook"].startswith("这条错误")
    assert policy["narrative_engine"] == "失败复盘"
    assert policy["motion_function"] == ["local_highlight", "type_in"]
    assert policy["transition_semantics"] == ["evidence_shock", "state_change"]
    assert policy["policy_hash"]
    assert policy["analysis_id"].startswith("viral:")
    assert "不得回退到标题加方块正文加底部字幕的默认骨架" in policy["anti_template_constraints"]


def test_policy_rejects_ready_without_accepted_evidence():
    bad = report()
    bad["summary"]["accepted_samples"] = 0
    with pytest.raises(ValueError, match="no_accepted_samples"):
        build_viral_execution_policy(bad, eligibility=eligibility())


def test_find_report_supports_platform_bundle():
    bundle = {"platforms": {"kuaishou": report()}}
    assert find_viral_report(bundle, "kuaishou")["status"] == "ready"
