import json

import pytest

from content_platform.overnight_topic_analysis import FIELDS, analyze_topic, flatten_scenario, parse_scenario


def _scenario(**overrides):
    data = {
        "domain": "office_automation",
        "actor": {"role": "后端工程师", "context": "维护带记忆的客服 Agent"},
        "inputs": [{"type": "对话日志", "source": "自有测试会话", "example_or_schema": "user_id, turn, text"}],
        "process": {"steps": [
            {"action": "抽取用户偏好", "ai_function": "总结多轮对话", "output": "偏好条目"},
            {"action": "写入知识库并检索", "ai_function": "向量检索", "output": "带引用的回答"},
        ]},
        "outcome": {"deliverable": "可检索的用户记忆", "measurement_method": "人工抽查 20 条回答",
                    "value_or_verification": "引用是否命中正确记忆", "responsible_role": "后端工程师",
                    "verification_action": "抽查并记录命中情况", "status": "measured"},
        "boundaries": [{"detail": "未验证生产规模下的延迟"}],
        "human_handoff": {"trigger": "记忆冲突", "responsible_role": "产品负责人",
                          "review_or_action": "确认保留哪条", "acceptance_or_escalation_rule": "未确认前不写入"},
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_parse_scenario_forces_verification_required_outcome():
    scenario = parse_scenario("```json\n" + _scenario() + "\n```")

    assert scenario["outcome"]["status"] == "verification_required"
    assert scenario["evidence_status"] == "verification_required"


def test_parse_scenario_rejects_a_single_step_process():
    with pytest.raises(ValueError, match="process_missing_or_nonoperational"):
        parse_scenario(_scenario(process={"steps": [{"action": "a", "ai_function": "b", "output": "c"}]}))


def test_parse_scenario_returns_none_when_source_is_ineligible():
    assert parse_scenario('{"eligible": false}') is None


def test_flatten_scenario_gives_the_six_blueprint_strings():
    flat = flatten_scenario(parse_scenario(_scenario()))

    assert set(flat) == set(FIELDS)
    assert "抽取用户偏好" in flat["process"] and "写入知识库并检索" in flat["process"]


def test_analyze_topic_sends_source_as_untrusted_observation():
    seen = {}

    def call(prompt, brief):
        seen["prompt"], seen["brief"] = prompt, brief
        return _scenario()

    candidate = {"title": "AI Agent 记忆", "url": "https://juejin.cn/post/1", "source": "juejin"}
    scenario = analyze_topic({}, "juejin", candidate, {}, call=call)

    assert scenario["domain"] == "office_automation"
    assert "untrusted observation" in seen["prompt"]
    assert "https://juejin.cn/post/1" in seen["prompt"]
    assert seen["brief"] == {"platform": "juejin", "topic": "AI Agent 记忆"}


def test_pet_lane_is_not_analysed_as_an_ai_scenario():
    assert analyze_topic({}, "douyin_pet", {"title": "猫"}, {}, call=lambda *a: pytest.fail("called")) is None
