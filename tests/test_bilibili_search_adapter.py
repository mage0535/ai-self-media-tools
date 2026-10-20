from content_platform.platform_hot_adapters import BilibiliSearchAdapter


def test_bilibili_public_search_emits_same_lane_work_snapshots_with_metrics():
    payload = {"code": 0, "data": {"result": [{"result_type": "video", "data": [
        {"bvid": "BV1work", "title": "AI辅助设备运维：振动异常交给工程师复核", "description": "传感器输入，生成维护建议和工单", "author": "工厂工程师", "mid": 7, "play": 6566, "like": 1219, "pubdate": 1760000000},
        {"bvid": "BV1news", "title": "最新大模型跑分榜单", "description": "模型新闻", "play": 99999, "like": 9999, "pubdate": 1760000000},
    ]}]}}
    report = BilibiliSearchAdapter(fetch_json=lambda _url: payload).collect(
        queries=["AI 工业质检 设备运维"], limit=10, lane="real_world_ai_implementation", order="click"
    )
    assert report["sources"][0]["status"] == "ok"
    assert report["sources"][0]["upstream_count"] == 2
    assert [row["content_id"] for row in report["items"]] == ["BV1work"]
    row = report["items"][0]
    assert row["metrics"] == {"views": 6566, "likes": 1219}
    assert row["published_at"] == "1760000000"
    assert row["native_verified"] is True
    assert row["generation_only"] is True
    assert row["auto_selection_eligible"] is False
