import json

import content_platform.real_world_ai_policy as real_world_ai_policy
import pytest

from content_platform.real_world_ai_policy import (
    classify_discovery_text,
    load_real_world_ai_positioning,
    validate_real_world_ai_package,
)


def test_positioning_applies_to_every_ai_channel():
    positioning = load_real_world_ai_positioning()
    assert positioning["policy_profile"] == "real_world_ai_implementation_v1"
    assert set(positioning["platforms"]) == {
        "douyin_ai", "kuaishou", "shipinhao", "wechat", "juejin", "zhihu",
        "bilibili", "tiktok", "youtube", "twitter", "threads", "bluesky",
        "mastodon", "nostr", "devto", "telegraph", "writeas", "buttondown",
    }


def test_positioning_loader_returns_isolated_data_and_observes_file_changes(tmp_path, monkeypatch):
    policy_path = tmp_path / "policy.json"
    policy = json.loads(real_world_ai_policy.POLICY_PATH.read_text(encoding="utf-8"))
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(real_world_ai_policy, "POLICY_PATH", policy_path)

    first = load_real_world_ai_positioning()
    first["pillars"].clear()
    policy["policy_revision"] = "changed-on-disk"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    second = load_real_world_ai_positioning()
    assert second["pillars"]
    assert second["policy_revision"] == "changed-on-disk"


def test_discovery_requires_ai_capability_and_concrete_application_scene():
    accepted = classify_discovery_text(
        "工业视觉质检：AI 如何复核涂装缺陷并把异常交给质检员确认",
        "输入为相机图像，输出为待人工复核的缺陷队列。",
    )
    rejected = classify_discovery_text("最新大模型发布：参数、跑分和榜单盘点", "模型能力新闻")
    english = classify_discovery_text("AI supply chain case study with productivity results")
    assert accepted["accepted"] is True
    assert english["accepted"] is True
    assert english["pillar"] == "industrial_application"
    assert rejected == {"accepted": False, "reason": "excluded_model_news_or_ranking"}


def test_discovery_rejects_bare_capability_scene_without_result_or_case_signal():
    assert classify_discovery_text("预测性维护") == {
        "accepted": False,
        "reason": "outcome_or_case_signal_missing",
    }


@pytest.mark.parametrize(
    "title",
    [
        "AI办公自动化十大工具清单：效率案例汇总",
        "AI合同审查Prompt合集：实战模板大全",
        "智能制造行业新闻速递：AI产线落地动态",
    ],
)
def test_discovery_prioritizes_rejection_of_lists_prompts_and_industry_news(title):
    result = classify_discovery_text(title)
    assert result == {"accepted": False, "reason": "excluded_tool_prompt_or_industry_news"}


def test_discovery_requires_review_when_multiple_pillars_match():
    result = classify_discovery_text(
        "AI智能制造与办公自动化联合案例",
        "产线设备数据同步到财务报表，复盘人工复核效果。",
    )
    assert result["accepted"] is False
    assert result["review_required"] is True
    assert result["reason"] == "multiple_application_scenes_require_review"
    assert set(result["matched_pillars"]) == {"intelligent_manufacturing", "office_automation"}


def test_publish_package_requires_one_concrete_scenario_and_human_handoff():
    package = {
        "policy_profile": "real_world_ai_implementation_v1",
        "scenario_count": 1,
        "scenario": {
            "domain": "office_automation",
            "actor": {"role": "财务专员", "context": "每周对账"},
            "inputs": [{"type": "xlsx", "source": "ERP 导出", "example_or_schema": "订单号、金额、日期"}],
            "process": {"steps": [
                {"action": "导入", "ai_function": "字段匹配", "output": "差异清单"},
                {"action": "复核", "ai_function": "异常归因草稿", "output": "待确认原因"},
            ]},
            "outcome": {"deliverable": "对账差异清单", "measurement_method": "与人工基线比较", "status": "verification_required", "value_or_verification": "记录每周处理时间", "responsible_role": "财务主管", "verification_action": "复核一周差异记录"},
            "boundaries": [{"type": "reliability", "detail": "金额异常必须人工复核"}],
            "human_handoff": {"trigger": "金额不一致", "responsible_role": "财务专员", "review_or_action": "核对原始凭证", "acceptance_or_escalation_rule": "确认后再入账"},
        },
    }
    assert validate_real_world_ai_package(package) == {"passed": True, "failures": []}
    del package["scenario"]["human_handoff"]
    assert "human_handoff_missing" in validate_real_world_ai_package(package)["failures"]


@pytest.mark.parametrize(
    ("status", "fields", "missing_field", "expected_failure"),
    [
        (
            "measured",
            {"source": "ERP 周报", "baseline": "人工耗时 4 小时", "metric": "处理时长", "measurement_method": "计时对比", "sample_or_period": "连续四周"},
            "source",
            "measured_outcome_evidence_missing",
        ),
        (
            "hypothesis",
            {"assumption": "字段格式保持稳定", "verification_plan": "抽取下周 50 条记录进行盲测"},
            "assumption",
            "hypothesis_contract_missing",
        ),
        (
            "verification_required",
            {"responsible_role": "财务主管", "verification_action": "逐项核对原始凭证"},
            "responsible_role",
            "verification_responsibility_missing",
        ),
    ],
)
def test_outcome_status_requires_its_status_specific_evidence(status, fields, missing_field, expected_failure):
    package = {
        "policy_profile": "real_world_ai_implementation_v1",
        "scenario_count": 1,
        "scenario": {
            "domain": "office_automation",
            "actor": {"role": "财务专员", "context": "每周对账"},
            "inputs": [{"type": "xlsx", "source": "ERP 导出", "example_or_schema": "订单号、金额、日期"}],
            "process": {"steps": [
                {"action": "导入", "ai_function": "字段匹配", "output": "差异清单"},
                {"action": "复核", "ai_function": "异常归因草稿", "output": "待确认原因"},
            ]},
            "outcome": {"deliverable": "对账差异清单", "measurement_method": "按状态约定执行", "status": status, "value_or_verification": "记录结果", **fields},
            "boundaries": [{"type": "reliability", "detail": "金额异常必须人工复核"}],
            "human_handoff": {"trigger": "金额不一致", "responsible_role": "财务专员", "review_or_action": "核对原始凭证", "acceptance_or_escalation_rule": "确认后再入账"},
        },
    }
    assert validate_real_world_ai_package(package)["passed"] is True

    del package["scenario"]["outcome"][missing_field]
    result = validate_real_world_ai_package(package)
    assert result["passed"] is False
    assert expected_failure in result["failures"]
