from content_platform.public_work_breakdown import build_public_work_breakdowns


def test_public_snapshot_is_materialized_without_inventing_deep_analysis():
    report = build_public_work_breakdowns({
        "observed_at": "2026-09-16T00:00:00+00:00",
        "items": [{
            "platform": "youtube", "content_id": "abc", "canonical_url": "https://youtube.test/watch?v=abc",
            "title": "Predictive Maintenance", "author": "Example", "metrics": {"views": 100},
            "source": "public", "collector": "metadata", "observed_at": "2026-09-16T00:00:00+00:00",
            "native_verified": True,
        }],
    })
    sample = report["samples"][0]
    assert report["status"] == "review_required"
    assert sample["decision"] == "review_required"
    assert sample["generation_only"] is True
    assert sample["deep_breakdown_status"] == "partial"
    assert "content_structure" in sample["missing_evidence"]
    assert "viral_conclusion" in sample["prohibited_claims"]


def test_public_breakdown_rejects_items_without_stable_work_identity():
    report = build_public_work_breakdowns({"items": [{"platform": "youtube", "title": "only a title"}]})
    assert report["status"] == "blocked"
    assert report["samples"] == []
