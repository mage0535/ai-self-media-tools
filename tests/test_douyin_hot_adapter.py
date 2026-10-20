from __future__ import annotations


def test_douyin_public_hot_adapter_emits_broad_ai_topic_signals_only():
    from content_platform.platform_hot_adapters import DouyinHotPageAdapter

    report = DouyinHotPageAdapter(fetch_json=lambda _url: {"data": {"word_list": [
        {"word": "AI智能体工作流", "hot_value": 987654, "label": "热", "url": "/search/AI智能体工作流"},
        {"word": "明星八卦", "hot_value": 876543, "label": "热", "url": "/search/明星八卦"},
    ]}}).collect(lane="broad_ai", lane_terms=["ai", "智能体"])

    assert report["sources"][0]["upstream_count"] == 2
    assert report["sources"][0]["count"] == 1
    row = report["items"][0]
    assert row["platform"] == "douyin"
    assert row["signal_type"] == "topic_signal"
    assert row["evidence_grade"] == "E1_topic_board"
    assert row["native_verified"] is True
    assert row["auto_selection_eligible"] is False
    assert row["metrics"] == {"heat_value": 987654}
    assert row["lane"] == "broad_ai"
    assert row["lane_match_terms"] == ["ai", "智能体"]


def test_douyin_real_world_lane_requires_an_ai_application_topic():
    from content_platform.platform_hot_adapters import DouyinHotPageAdapter

    report = DouyinHotPageAdapter(fetch_json=lambda _url: {"data": {"word_list": [
        {"word": "AI辅助设备运维：传感器异常交给工程师复核", "hot_value": 987654},
        {"word": "最新大模型跑分榜单", "hot_value": 876543},
    ]}}).collect(lane="real_world_ai_implementation")

    assert report["sources"][0]["count"] == 1
    assert report["items"][0]["positioning"]["pillar"] == "industrial_application"
    assert report["items"][0]["auto_selection_eligible"] is False

