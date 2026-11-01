import copy

import pytest

from content_platform.content_blueprint import build_content_blueprint
from content_platform.creative_strategy import (
    load_catalog,
    resolve_combination,
    select_combination,
    story_beats,
    validate_catalog,
)
from content_platform.generator import _with_creative_rules
from tests.test_content_blueprint import SCENARIO


def test_catalog_is_valid_layered_and_sourced():
    catalog = load_catalog()
    assert validate_catalog(catalog)["passed"]
    for layer in catalog["layers"]:
        assert sum(entry["layer"] == layer for entry in catalog["entries"]) >= 3


def test_catalog_rejects_repost_rules_and_unsourced_entries():
    catalog = copy.deepcopy(load_catalog())
    catalog["entries"][0]["rule"] = "搬运热门视频后去重"
    catalog["entries"][1]["sources"] = ["unknown"]
    failures = validate_catalog(catalog)["failures"]
    assert any(item.startswith("forbidden_rule:") for item in failures)
    assert any(item.startswith("source_missing:") for item in failures)


def test_video_selection_picks_every_layer_and_three_shots_deterministically():
    first = select_combination("kuaishou", "律师用AI整理尽调材料", content_form="short_video")
    again = select_combination("kuaishou", "律师用AI整理尽调材料", content_form="short_video")
    assert first == again
    assert set(first["picks"]) == {"angle", "narrative", "hook", "structure", "voice", "shot", "character", "cover"}
    assert len(first["picks"]["shot"]) == 3 and len(set(first["picks"]["shot"])) == 3
    assert first["goal"] == "completion"


def test_article_selection_has_no_shot_layer_and_article_only_structure():
    combination = select_combination("wechat", "会计月结用AI核对凭证", content_form="long_article")
    assert "shot" not in combination["picks"]
    catalog = load_catalog()
    structure = next(entry for entry in catalog["entries"] if entry["id"] == combination["picks"]["structure"])
    assert "*" in structure["forms"] or "article" in structure["forms"]


def test_recent_history_moves_selection_to_a_different_combination():
    topic = "运营用AI写周报"
    first = select_combination("douyin_ai", topic, content_form="short_video")
    second = select_combination("douyin_ai", topic, content_form="short_video", history=[first])
    assert second["picks"]["narrative"] != first["picks"]["narrative"]
    assert second["picks"]["hook"] != first["picks"]["hook"]


def test_pet_lane_never_gets_ai_only_entries_and_episodic_needs_series_bible():
    catalog = load_catalog()
    ai_only = {entry["id"] for entry in catalog["entries"] if entry["lanes"] == ["real_world_ai_implementation"]}
    history = []
    for index in range(6):
        combination = select_combination("douyin_pet", f"猫咪踩奶的原因{index}", content_form="short_video", history=history)
        history.insert(0, combination)
        picked = {value for value in combination["picks"].values() if isinstance(value, str)}
        assert not picked & ai_only
        assert combination["picks"]["narrative"] != "narrative.episodic_series"
    fresh = select_combination("douyin_pet", "猫咪为什么总踩奶", content_form="short_video")
    assert fresh["picks"]["voice"] == "voice.warm_healing" and fresh["picks"]["cover"] == "cover.pet_hero"
    with_bible = select_combination("douyin_pet", "猫咪踩奶的原因", content_form="short_video",
                                    capabilities={"series_bible"}, history=history)
    assert with_bible["lane"] == "pet_healing"


def test_resolve_refuses_combination_from_a_changed_catalog():
    combination = select_combination("zhihu", "医生用AI整理病历摘要", content_form="evidence_answer")
    changed = dict(combination, catalog_sha256="0" * 64)
    with pytest.raises(ValueError, match="creative_catalog_changed"):
        resolve_combination(changed)


def test_blueprint_uses_story_beats_and_generator_expands_rules():
    combination = select_combination("tiktok", "AI meeting notes", content_form="short_video")
    slot = {"audience": "busy teams", "user_pain": "summaries do not become actions", "content_form": "short_video",
            "topic_keywords": ["AI"], "scenario_contract": SCENARIO, "creative_combination": combination,
            "subtitle_and_pacing_plan": {"segments": [{"start": 0, "end": 3, "text": "Who owns this decision?"}]}}
    blueprint = build_content_blueprint("tiktok", "AI meeting notes", slot,
                                        {"trend_evidence": {"samples": [{"url": "https://example.test/trend"}]}})
    assert blueprint["creative_combination"] == combination
    assert blueprint["story_beats"] == story_beats(combination) and len(blueprint["story_beats"]) >= 5
    assert blueprint["narrative_structure"][0] == "hook"
    payload = _with_creative_rules({"content_blueprint": blueprint})
    rules = payload["content_blueprint"]["creative_rules"]
    assert set(combination["picks"]) <= set(rules)
    assert isinstance(rules["shot"], list) and len(rules["shot"]) == 3
    assert "evidence" in rules["use"]


def test_strategy_structure_pool_and_evidence_shift_selection_and_are_recorded():
    catalog = load_catalog()
    topic = "财务用AI对账"
    plain = select_combination("zhihu", topic, content_form="evidence_answer")
    pool = ["controversial_viewpoint"]
    weighted = select_combination("zhihu", topic, content_form="evidence_answer",
                                  strategy={"structure_pool": pool, "source_sha256": "a" * 64})
    tagged = {entry["id"] for entry in catalog["entries"] if set(pool) & set(entry.get("strategy_tags") or [])}
    picked = {value for value in weighted["picks"].values() if isinstance(value, str)}
    assert picked & tagged
    assert weighted["inputs"]["strategy_sha256"] == "a" * 64 and weighted["inputs"]["strategy_structures"] == 1
    assert plain["inputs"]["strategy_structures"] == 0
    with_evidence = select_combination("zhihu", topic, content_form="evidence_answer", evidence_text="真相 结局 原来")
    assert with_evidence["inputs"]["evidence_chars"] > 0


def test_short_post_platforms_get_post_form_without_shots():
    combination = select_combination("twitter", "AI meeting notes", content_form="short_post")
    assert combination["form"] == "post" and "shot" not in combination["picks"]
    assert {"angle", "hook", "voice"} <= set(combination["picks"])


def test_video_planning_payload_carries_story_direction_for_our_own_script():
    from content_platform.run_contract import build_run_contract
    from content_platform.video_planning_producer import analysis_payload

    combination = select_combination("kuaishou", "律师用AI整理尽调材料", content_form="short_video")
    contract = build_run_contract("kuaishou")
    plain = analysis_payload(contract, "律师用AI整理尽调材料", [])
    directed = analysis_payload(contract, "律师用AI整理尽调材料", [], combination)
    assert "creative_rules" not in plain["content_blueprint"]
    blueprint = directed["content_blueprint"]
    assert blueprint["story_beats"] == story_beats(combination)
    assert set(combination["picks"]) <= set(blueprint["creative_rules"])
    assert "replaces any generic" in blueprint["creative_rules"]["use"]
