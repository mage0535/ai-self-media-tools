from datetime import datetime, timedelta, timezone

from content_platform.topic_ranker_v2 import rank_topic_candidates, score_topic_candidate


def test_native_official_signal_beats_external_reference():
    rows = [
        {"title": "AI工具实测", "source": "github", "points": 500, "platform": "kuaishou"},
        {"title": "AI工具实测", "source": "kuaishou:official", "points": 120, "platform": "kuaishou", "official_reference_only": True, "associated_hotspot": {"platform": "kuaishou", "hotspot_id": "ks-ai", "title": "AI工具", "native_verified": True, "heat_score": 0.9, "lane_fit_score": 0.9, "semantic_fit_score": 0.9, "expires_at": (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}},
    ]
    ranked = rank_topic_candidates(rows, {"platform": "kuaishou", "keywords": ["ai", "工具"]})
    assert ranked[0]["source"] == "kuaishou:official"
    assert ranked[0]["score_breakdown"]["official_signal"] > 0


def test_expired_official_signal_is_not_eligible():
    row = {"title": "AI工具", "platform": "kuaishou", "source": "kuaishou:official", "official_reference_only": True, "associated_hotspot": {"platform": "kuaishou", "hotspot_id": "old", "title": "AI工具", "native_verified": True, "heat_score": 1, "lane_fit_score": 1, "semantic_fit_score": 1, "expires_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}}
    result = score_topic_candidate(row, {"platform": "kuaishou", "keywords": ["ai", "工具"]})
    assert result["eligible"] is False
    assert "hotspot_expired" in result["reasons"]


def test_cross_platform_official_identity_is_rejected():
    row = {"title": "AI工具", "platform": "douyin_ai", "source": "kuaishou:official", "official_reference_only": True, "associated_hotspot": {"platform": "kuaishou", "hotspot_id": "ks", "title": "AI工具", "native_verified": True, "heat_score": .9, "lane_fit_score": .9, "semantic_fit_score": .9}}
    result = score_topic_candidate(row, {"platform": "douyin_ai", "keywords": ["ai", "工具"]})
    assert result["eligible"] is False
    assert "hotspot_platform_mismatch" in result["reasons"]


def test_rank_trends_v2_uses_platform_native_scoring():
    from content_platform.trends import rank_trends
    rows = [{"title": "AI工具教程", "source": "kuaishou:official", "platform": "kuaishou", "points": 10, "official_reference_only": True, "associated_hotspot": {"platform": "kuaishou", "hotspot_id": "ks", "title": "AI工具", "native_verified": True, "heat_score": .9, "lane_fit_score": .9, "semantic_fit_score": .9}}]
    result = rank_trends(rows, {"platform": "kuaishou", "keywords": ["ai", "工具"], "topic_scoring_mode": "v2"})
    assert result[0]["score_breakdown"]["official_signal"] == 1.0


def test_native_chinese_keyword_uses_hotspot_lane_fit_without_english_keyword_match():
    row = {"title": "人工智能", "source": "kuaishou:official", "platform": "kuaishou", "official_reference_only": True, "associated_hotspot": {"platform": "kuaishou", "hotspot_id": "ks-ai-cn", "title": "人工智能", "native_verified": True, "heat_score": .9, "lane_fit_score": .9, "semantic_fit_score": .9}}
    result = score_topic_candidate(row, {"platform": "kuaishou", "keywords": ["AI", "workflow"]})
    assert result["eligible"] is True
    assert result["score_breakdown"]["lane_fit"] >= .8
