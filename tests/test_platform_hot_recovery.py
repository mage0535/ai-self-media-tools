from __future__ import annotations


def test_hot_evidence_cli_and_bundle_contract_are_available():
    from content_platform.cli import parser
    from content_platform.platform_hot_adapters import collect_platform_hot_evidence

    args = parser().parse_args(
        [
            "hot-evidence-collect",
            "--source-config",
            "/tmp/hot-sources.json",
            "--output",
            "/tmp/hot-evidence.json",
        ]
    )
    bundle = collect_platform_hot_evidence(
        {"platforms": ["bilibili"], "dailyhot": {"enabled": True, "base_url": "https://dailyhot.example"}},
        fetch_json=lambda _url: {
            "updateTime": "2026-09-15T00:00:00Z",
            "data": [
                {
                    "id": "BV1example",
                    "title": "AI 工厂质检实战",
                    "url": "https://www.bilibili.com/video/BV1example",
                    "hot": 120000,
                }
            ],
        },
    )

    assert args.command == "hot-evidence-collect"
    assert bundle["version"] == "platform_hot_evidence_bundle_v1"
    assert bundle["items"][0]["canonical_url"] == "https://www.bilibili.com/video/BV1example"
    assert bundle["items"][0]["auto_selection_eligible"] is False


def test_evidence_bundle_becomes_generation_only_hot_work_context(tmp_path):
    import json
    from content_platform.hot_work_intelligence import import_platform_hot_evidence_bundle

    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"items": [{
        "platform": "bilibili",
        "title": "AI 工作流实测",
        "canonical_url": "https://www.bilibili.com/video/BV1example",
        "signal_type": "ranked_content_candidate",
        "source": "bilibili_popular_api",
        "collector": "bilibili_popular_api",
        "observed_at": "2026-09-15T00:00:00+00:00",
        "raw_response_hash": "a" * 64,
        "metrics": {"views": 120000, "likes": 5000},
        "native_verified": True,
        "auto_selection_eligible": False,
    }]}), encoding="utf-8")

    rows, statuses = import_platform_hot_evidence_bundle(evidence)

    assert len(rows) == 1
    assert rows[0]["hot_evidence_bucket"] == "ranked_content_candidates"
    assert rows[0]["generation_only"] is True
    assert rows[0]["auto_selection_eligible"] is False
    assert statuses[0]["status"] == "ok"


def test_bilibili_popular_adapter_filters_to_broad_ai_lane_with_match_evidence():
    from content_platform.platform_hot_adapters import BilibiliPopularAdapter

    report = BilibiliPopularAdapter(fetch_json=lambda _url: {"code": 0, "data": {"list": [
        {"bvid": "BVai", "title": "AI Agent 工程化实战", "desc": "大模型工作流部署", "owner": {"name": "AI作者"}, "stat": {}},
        {"bvid": "BVgame", "title": "热门游戏实况", "desc": "全程高能", "owner": {"name": "游戏作者"}, "stat": {}},
    ]}}).collect(limit=10, lane="broad_ai", lane_terms=["ai", "大模型", "智能体"])

    assert [row["content_id"] for row in report["items"]] == ["BVai"]
    assert report["items"][0]["lane"] == "broad_ai"
    assert report["items"][0]["lane_match_terms"] == ["ai", "大模型"]
    assert report["sources"][0]["upstream_count"] == 2
    assert report["sources"][0]["count"] == 1




def test_bilibili_real_world_lane_accepts_one_maintenance_workflow_and_rejects_model_news():
    from content_platform.platform_hot_adapters import BilibiliPopularAdapter

    report = BilibiliPopularAdapter(fetch_json=lambda _url: {"code": 0, "data": {"list": [
        {"bvid": "BVworkflow", "title": "AI 如何辅助设备运维：振动异常交给工程师复核", "desc": "传感器输入与预测性维护工单", "owner": {}, "stat": {}},
        {"bvid": "BVnews", "title": "最新大模型发布与跑分榜单", "desc": "模型新闻", "owner": {}, "stat": {}},
    ]}}).collect(lane="real_world_ai_implementation")

    assert [row["content_id"] for row in report["items"]] == ["BVworkflow"]
    assert report["items"][0]["positioning"]["pillar"] == "industrial_application"


def test_bilibili_official_popular_adapter_preserves_work_metrics():
    from content_platform.platform_hot_adapters import BilibiliPopularAdapter

    report = BilibiliPopularAdapter(fetch_json=lambda _url: {"code": 0, "data": {"list": [{
        "bvid": "BV1example",
        "title": "AI 工作流实测",
        "desc": "完整演示",
        "pubdate": 1757808000,
        "owner": {"mid": 7, "name": "测试作者"},
        "stat": {"view": 120000, "like": 5000, "coin": 300, "favorite": 900, "reply": 80, "share": 60},
    }]}}).collect(limit=10)

    row = report["items"][0]
    assert row["canonical_url"] == "https://www.bilibili.com/video/BV1example"
    assert row["metrics"]["views"] == 120000
    assert row["native_verified"] is True
    assert row["auto_selection_eligible"] is False
