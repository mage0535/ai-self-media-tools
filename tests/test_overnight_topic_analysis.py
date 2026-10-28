import json

import pytest

from content_platform.overnight_topic_analysis import FIELDS, analyze_topic, parse_scenario


def _answer(**overrides):
    data = {key: f"{key} concrete detail for the selected topic" for key in FIELDS}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_parse_scenario_returns_all_six_fields():
    scenario = parse_scenario("```json\n" + _answer() + "\n```")

    assert set(scenario) == set(FIELDS)


def test_parse_scenario_rejects_missing_or_short_fields():
    with pytest.raises(ValueError, match="topic_analysis_fields_invalid:boundaries"):
        parse_scenario(_answer(boundaries="short"))


def test_parse_scenario_returns_none_when_source_is_ineligible():
    assert parse_scenario('{"eligible": false}') is None


def test_analyze_topic_sends_source_as_untrusted_observation():
    seen = {}

    def call(prompt, brief):
        seen["prompt"], seen["brief"] = prompt, brief
        return _answer()

    candidate = {"title": "AI Agent 记忆", "url": "https://juejin.cn/post/1", "source": "juejin"}
    scenario = analyze_topic({}, "juejin", candidate, {}, call=call)

    assert scenario["actor"].startswith("actor")
    assert "untrusted observation" in seen["prompt"]
    assert "https://juejin.cn/post/1" in seen["prompt"]
    assert "Simplified Chinese" in seen["prompt"]
    assert seen["brief"] == {"platform": "juejin", "topic": "AI Agent 记忆"}
