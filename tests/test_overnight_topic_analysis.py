import json

import pytest

from content_platform.overnight_topic_analysis import FIELDS, analyze_topic, flatten_scenario, parse_scenario, video_pacing_plan


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


def test_flatten_scenario_is_bounded_for_the_payload_limit():
    long = "很长的说明" * 40
    steps = [{"action": long, "ai_function": "x", "output": long} for _ in range(6)]
    flat = flatten_scenario(parse_scenario(_scenario(
        inputs=[{"type": long, "source": "s", "example_or_schema": long}] * 5,
        process={"steps": steps}, boundaries=[{"detail": long}] * 5)))

    weights = {"actor": 4, "inputs": 5, "process": 7, "outcome": 6, "boundaries": 9, "human_handoff": 3}
    assert flat["process"].count("→") == 3
    # Blueprint reuse weights: worst case must stay well inside the 16 KB generate payload.
    assert sum(len(flat[key].encode("utf-8")) * weight for key, weight in weights.items()) <= 7000


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


PET = {
    "domain": "cat_care_avoidance_manual",
    "actor": {"role": "新手猫主人", "context": "第一次给猫换粮"},
    "inputs": [{"type": "视频观察", "source": "热门视频", "example_or_schema": "猫闻粮后走开"}],
    "process": {"steps": [{"action": "新旧粮按比例混合", "output": "七天换粮表"},
                          {"action": "观察便便和食欲", "output": "每日记录"}]},
    "outcome": {"deliverable": "换粮避坑清单", "value_or_verification": "主人对照记录自查"},
    "boundaries": [{"detail": "持续腹泻须就医"}],
    "human_handoff": {"trigger": "呕吐或拒食", "responsible_role": "宠物医生",
                      "review_or_action": "检查肠胃", "acceptance_or_escalation_rule": "两天无改善即就诊"},
}


def test_pet_lane_uses_the_pet_prompt_and_its_own_domains():
    prompts = []
    scenario = analyze_topic({}, "douyin_pet", {"title": "猫换粮"}, {},
                             call=lambda prompt, meta: prompts.append(prompt) or json.dumps(PET, ensure_ascii=False))
    assert "healing cat-and-dog account" in prompts[0] and "office_automation" not in prompts[0]
    assert scenario["outcome"]["status"] == "verification_required"
    assert set(flatten_scenario(scenario)) == set(FIELDS)


def test_pet_scenario_outside_the_pet_domains_is_rejected():
    with pytest.raises(ValueError, match="domain_out_of_scope"):
        analyze_topic({}, "douyin_pet", {"title": "猫"}, {},
                      call=lambda *a: json.dumps(dict(PET, domain="office_automation")))


def test_video_pacing_plan_lets_a_video_blueprint_pass():
    from content_platform.content_blueprint import build_content_blueprint

    scenario = parse_scenario(_scenario())
    plan = video_pacing_plan("douyin_ai", "AI 记忆", scenario)
    assert plan["timing_status"] == "unmeasured_until_actual_full_track_render"
    assert [row["role"] for row in plan["segments"]] == ["hook", "problem", "method", "method", "result", "handoff"]
    slot = {"stage": "handoff_video", "scenario_contract": flatten_scenario(scenario),
            "subtitle_and_pacing_plan_when_video": plan}
    matrix = {"trend_evidence": {"samples": [{"url": "https://www.bilibili.com/video/BV1"}]}}
    blueprint = build_content_blueprint("douyin_ai", "AI 记忆", slot, matrix)
    assert blueprint["subtitle_and_pacing_plan_when_video"] == plan


def test_topic_analysis_prompt_carries_account_positioning_and_exclusions():
    from content_platform.overnight_topic_analysis import build_prompt

    prompt = build_prompt("zhihu", {"title": "AI 质检落地复盘"}, {})
    assert "一篇只解决一个主场景" in prompt and "Never dress such a source up as a case" in prompt
    assert "model release" in prompt and "tool or prompt list" in prompt
