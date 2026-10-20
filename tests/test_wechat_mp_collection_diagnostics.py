from __future__ import annotations

from scripts.wechat_mp_backend_collector import build_article_collection_audit


def test_article_collection_audit_reports_only_safe_counts():
    audit = build_article_collection_audit(
        {"article_list": [{"msg_id": "one"}, {"msg_id": "two"}]},
        {"one:1": {"link": "https://mp.weixin.qq.com/s/one"}},
        [{"title": "sensitive title must not appear"}],
        account_name="马吉克AI",
        article_analysis_requested=True,
    )

    assert audit == {
        "article_analysis_row_count": 2,
        "article_index_count": 1,
        "article_observation_count": 1,
        "account_name_provided": True,
        "article_analysis_requested": True,
        "article_analysis_base_ret": None,
        "article_analysis_error": "",
    }
    assert "sensitive title" not in str(audit)
