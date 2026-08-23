from datetime import datetime, timedelta, timezone

from content_platform.trends import rank_trends


def test_rank_trends_applies_verified_hotspot_bonus_and_rejects_invalid_association():
    base = {
        "title": "AI workflow",
        "source": "douyin",
        "points": 100,
        "associated_hotspot": {
            "platform": "douyin_ai",
            "hotspot_id": "h1",
            "title": "AI workflow",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "native_verified": True,
            "association_mode": "manual_handoff",
            "heat_rank": 1,
            "heat_score": 0.9,
            "lane_fit_score": 0.9,
            "semantic_fit_score": 0.9,
        },
    }
    ranked = rank_trends([base], {"keywords": ["AI"], "source_weights": {"douyin": 1}}, used=set(), limit=1)
    assert ranked[0]["hotspot_bonus"] > 0
    invalid = dict(base, associated_hotspot=dict(base["associated_hotspot"], native_verified=False))
    assert rank_trends([invalid], {"keywords": ["AI"], "source_weights": {"douyin": 1}}, used=set(), limit=1) == []
