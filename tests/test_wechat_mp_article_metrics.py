from __future__ import annotations

from scripts.wechat_mp_backend_collector import build_article_metric_observations


def test_article_analysis_becomes_auditable_g4_candidate_observations():
    records = build_article_metric_observations(
        {
            "article_list": [
                {
                    "msg_id": "123456",
                    "item_idx": 1,
                    "title": "AI 工作流别急着全自动",
                    "ref_date": "2026-09-15",
                    "total_read_uv": 4321,
                    "read_uv_ratio": 0.18,
                }
            ]
        },
        {"123456:1": {"link": "https://mp.weixin.qq.com/s?example", "create_time": 1757808000}},
        account_name="我的公众号",
        observed_at="2026-09-15T06:00:00+00:00",
    )

    assert len(records) == 1
    row = records[0]
    assert row["source_kind"] == "authorized_backend_export"
    assert row["canonical_url"] == "https://mp.weixin.qq.com/s?example"
    assert row["metric_name"] == "total_read_uv"
    assert row["metric_value"] == 4321
    assert row["metric_definition"] == "Unique readers shown by authorized WeChat MP article analysis"
    assert row["observed_at"] == "2026-09-15T06:00:00+00:00"
    assert row["account_name"] == "我的公众号"
    assert row["baseline_required"] is True


def test_article_analysis_drops_rows_without_stable_identity_or_metric():
    records = build_article_metric_observations(
        {"article_list": [{"msg_id": "", "item_idx": 1, "title": "missing", "total_read_uv": 9}]},
        {},
        account_name="我的公众号",
        observed_at="2026-09-15T06:00:00+00:00",
    )
    assert records == []
