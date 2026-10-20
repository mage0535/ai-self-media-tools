from content_platform.platform_hot_adapters import ZhihuOpenHotAdapter


class _FakeZhihuClient:
    def trending(self, limit=20):
        return []

    def search(self, query, limit=10, scope="zhihu"):
        return [{
            "title": "设备运维：AI 分析振动告警并交给工程师复核",
            "url": "https://www.zhihu.com/question/1/answer/2",
            "type": "Article",
            "author": "测试作者",
            "content_excerpt": "输入是传感器告警，输出为待人工确认的维护工单。",
            "points": 3,
            "comment_count": 1,
        }]


def test_zhihu_search_rows_include_fail_closed_evidence_triage():
    report = ZhihuOpenHotAdapter(client=_FakeZhihuClient()).collect(queries=["AI 设备运维"], hot_limit=1, search_limit=1)
    row = report["items"][0]
    assert row["signal_type"] == "public_work_metadata_snapshot"
    assert row["evidence_triage"]["tier"] == "research_candidate"
    assert row["evidence_triage"]["viral_claim_eligible"] is False
    assert row["auto_selection_eligible"] is False
