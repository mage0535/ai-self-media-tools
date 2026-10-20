import json

from content_platform.same_lane_intelligence import (
    compact_same_lane_playbook,
    distill_same_lane_samples,
    filter_rankable_samples,
    load_samples_file,
)


def test_loads_top_level_wechat_articles_as_wechat_samples(tmp_path):
    source = tmp_path / "wechat_native.json"
    source.write_text(
        json.dumps(
            {
                "query": "AI 大模型",
                "articles": [
                    {
                        "title": "多模态模型发布后的真实变化",
                        "source": "AI前线",
                        "datetime": "2026-09-15 10:00:00",
                        "summary": "大模型与多模态能力实测。",
                        "url": "https://mp.weixin.qq.com/s/example",
                        "url_resolved": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = load_samples_file(source)

    assert len(loaded["wechat"]) == 1
    sample = loaded["wechat"][0]
    assert sample["account"] == "AI前线"
    assert sample["published_at"] == "2026-09-15 10:00:00"
    assert sample["source_query"] == "AI 大模型"
    assert sample["url_resolved"] is True


def test_real_world_ai_application_accepts_concrete_scene_and_rejects_generic_tool_content():
    accepted, rejected = filter_rankable_samples(
        "wechat",
        [
            {
                "title": "财务对账：AI 如何标记 ERP 导出中的异常订单，交给专员复核",
                "summary": "输入为订单和回款数据，输出为待人工确认的差异清单。",
                "url": "https://mp.weixin.qq.com/s/real-workflow",
            },
            {
                "title": "办公室效率工具合集",
                "summary": "整理、日程和文件管理技巧。",
                "url": "https://mp.weixin.qq.com/s/generic-tool",
            },
        ],
    )

    assert [row["title"] for row in accepted] == ["财务对账：AI 如何标记 ERP 导出中的异常订单，交给专员复核"]
    assert accepted[0]["positioning"]["pillar"] == "office_automation"
    assert rejected[0]["reject_reason"] == "excluded_tool_prompt_or_industry_news"


def test_metricless_native_wechat_ai_article_is_discovery_only():
    report = distill_same_lane_samples(
        "wechat",
        [
            {
                "title": "设备运维：AI 识别压缩机振动异常后交给工程师确认",
                "summary": "输入为设备传感器数据，输出为待人工复核的预测性维护工单。",
                "url": "https://mp.weixin.qq.com/s/robotics",
                "published_at": "2026-09-15T10:00:00+08:00",
            }
        ],
    )

    assert report["radar"]["status"] == "discovery_only"
    assert report["radar"]["discovery_sample_count"] == 1
    assert report["radar"]["ranked_sample_count"] == 0
    assert report["top_works"] == []
    assert report["generation_status"] == "research_required"
    assert report["topic_patterns"] == []
    assert report["recommended_content_moves"] == []
    assert report["hook_patterns"] == []
    assert report["structure_patterns"] == []
    assert report["visual_patterns"] == []
    compact = compact_same_lane_playbook(report)
    assert compact["status"] == "discovery_only"
    assert compact["gate_failures"] == ["metrics_missing", "insufficient_ranked_samples"]
