import json
import re
from pathlib import Path

from content_platform.real_world_ai_policy import build_discovery_queries


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "real_world_ai_implementation_v1.json"
RULEBOOK_PATH = ROOT / "config" / "channel_content_rulebook.json"

AI_PLATFORMS = {
    "douyin_ai",
    "kuaishou",
    "shipinhao",
    "wechat",
    "juejin",
    "zhihu",
    "bilibili",
    "tiktok",
    "youtube",
    "twitter",
    "threads",
    "bluesky",
    "mastodon",
    "nostr",
    "devto",
    "telegraph",
    "writeas",
    "buttondown",
}
EXPECTED_PILLARS = {
    "industrial_application",
    "intelligent_manufacturing",
    "office_automation",
    "daily_life_application",
}
REQUIRED_SCENARIO_FIELDS = {
    "actor",
    "inputs",
    "process",
    "outcome",
    "boundaries",
    "human_handoff",
}


def test_every_ai_platform_uses_the_single_real_world_ai_contract():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))

    assert set(policy["platforms"]) == AI_PLATFORMS
    assert set(policy["pillars"]) == EXPECTED_PILLARS

    expected_ref = {
        "source": "config/real_world_ai_implementation_v1.json",
        "policy_profile": policy["policy_profile"],
        "policy_revision": policy["policy_revision"],
    }
    for platform in sorted(AI_PLATFORMS):
        rule = rulebook["channel_rules"][platform]
        assert rule["lane"] == "real_world_ai_implementation_v1", platform
        positioning = rule["real_world_ai_positioning"]
        assert positioning["canonical_contract"] == expected_ref, platform
        assert positioning["platform_adaptation"] == policy["platform_adaptation"][platform], platform
        assert "content_pillars" not in positioning, platform
        assert "required_content_contract" not in positioning, platform
        assert "disallowed_content" not in positioning, platform


def test_discovery_terms_are_policy_driven_capability_x_scene_x_result():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert policy["ai_capability_terms"]
    assert all(policy["pillars"].values())
    assert policy["outcome_case_terms"]
    combination = policy["discovery_query_contract"]
    assert combination["required_groups"] == [
        "ai_capability_terms",
        "pillar_terms",
        "outcome_case_terms",
    ]
    assert combination["dynamic_combination"] is True
    assert combination["single_group_query_forbidden"] is True


def test_dynamic_queries_do_not_mix_domestic_and_international_languages():
    zh_queries = build_discovery_queries(seed="contract-test", language="zh")
    en_queries = build_discovery_queries(seed="contract-test", language="en")

    assert len(zh_queries) == len(EXPECTED_PILLARS)
    assert len(en_queries) == len(EXPECTED_PILLARS)
    assert all(re.search(r"[\u4e00-\u9fff]", query) for query in zh_queries)
    assert all(not re.search(r"[\u4e00-\u9fff]", query) for query in en_queries)


def test_generation_contract_preserves_the_users_hard_constraints():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    contract = policy["content_contract"]

    assert contract["one_primary_scenario"] is True
    assert REQUIRED_SCENARIO_FIELDS == set(contract["required"])
    assert contract["verified_evidence_or_explicit_assumption"] is True
    assert contract["artifact_alignment_required"] == [
        "title",
        "opening",
        "visuals",
        "body_structure",
        "cta",
    ]
    assert contract["platform_may_change_format_but_not_lane"] is True


def test_nested_douyin_ai_account_cannot_fall_back_to_legacy_lane():
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    account = rulebook["account_lane_separation_policy"]["accounts"]["douyin_ai"]

    assert account["lane"] == "real_world_ai_implementation_v1"
    assert account["real_world_ai_positioning"]["canonical_contract"]["policy_profile"] == "real_world_ai_implementation_v1"
    assert "allowed_content_lines" not in account
    assert "policy_profile" not in account
    assert "ai_efficiency_open_source" not in json.dumps(account, ensure_ascii=False)
