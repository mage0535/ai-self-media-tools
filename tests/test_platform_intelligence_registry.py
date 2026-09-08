from content_platform.content_policy import DELIVERY_MODES
from content_platform.platform_intelligence_registry import (
    load_platform_intelligence_registry,
    platform_queries,
    publishing_platforms,
    reference_source_configs,
)


EXPECTED_TARGETS = {
    "wechat", "kuaishou", "juejin", "twitter", "douyin_ai", "douyin_pet",
    "shipinhao", "xiaohongshu", "bilibili", "zhihu", "youtube", "tiktok",
}


def test_registry_covers_every_canonical_delivery_target_with_collectors_and_queries():
    registry = load_platform_intelligence_registry()

    assert set(publishing_platforms()) == EXPECTED_TARGETS
    assert EXPECTED_TARGETS.issubset(DELIVERY_MODES)
    assert all(registry["publish_targets"][name]["collectors"] for name in EXPECTED_TARGETS)
    assert all(platform_queries(name) for name in EXPECTED_TARGETS)


def test_registry_expands_domestic_and_international_reference_sources_without_native_identity():
    rows = reference_source_configs()

    assert {"weibo", "baidu", "toutiao", "csdn", "36kr"}.issubset(rows)
    assert {"github", "hackernews", "reddit", "producthunt", "devto", "medium"}.issubset(rows)
    assert {row["region"] for row in rows.values()} == {"cn", "intl"}
    assert all(row["identity_role"] == "cross_platform_reference" for row in rows.values())
