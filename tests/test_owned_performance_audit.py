from content_platform.owned_performance_audit import audit_owned_performance_rows


def test_audit_uses_local_job_id_only_for_owned_review_and_quarantines_impossible_metrics():
    report = audit_owned_performance_rows([
        {"platform": "juejin", "job_id": "j1", "title": "", "views": 5900000, "likes": 5900000},
        {"platform": "youtube", "job_id": "y1", "title": "AI 质检复盘", "views": 120, "likes": 4},
    ])

    assert report["eligible_count"] == 1
    assert report["quarantined_count"] == 1
    assert report["quarantined"][0]["reason_codes"] == ["likes_not_less_than_views"]
    assert report["eligible"][0]["job_id"] == "y1"
