from datetime import datetime, timezone

from content_platform.platform_intelligence_state import evaluate_platform_intelligence


def _snapshot(*, observed_at: str, views: int, content_id: str = "video-1") -> dict:
    return {
        "platform": "youtube",
        "content_id": content_id,
        "canonical_url": f"https://www.youtube.com/watch?v={content_id}",
        "author": "Owned Channel",
        "published_at": "2026-09-01T00:00:00+00:00",
        "observed_at": observed_at,
        "metrics": {"views": views, "likes": views // 10},
        "raw_response_hash": "a" * 64,
        "native_verified": True,
    }


def _content_evidence() -> dict:
    return {
        "body_verified": True,
        "evidence_refs": [
            {"kind": "native_transcript", "sha256": "b" * 64, "source_url": "https://www.youtube.com/watch?v=video-1"},
            {"kind": "frame_manifest", "sha256": "c" * 64, "source_url": "file:///authorized/video-1/frames.json"},
        ],
    }


def _ready_breakdown() -> dict:
    return {
        "status": "ready",
        "validation": {"passed": True},
        "platform": "youtube",
        "lane": "real_world_ai_implementation",
        "cache": {"expires_at": "2026-09-20T00:00:00+00:00", "ttl_days": 7},
        "summary": {"accepted_samples": 1},
        "samples": [{"reference_ids": ["video-1"], "raw_snapshot_ref": "a" * 64}],
    }


def test_evaluator_reaches_dual_snapshot_only_for_comparable_verified_work():
    result = evaluate_platform_intelligence(
        platform="youtube",
        lane="real_world_ai_implementation",
        snapshots=[
            _snapshot(observed_at="2026-09-15T00:00:00+00:00", views=100),
            _snapshot(observed_at="2026-09-15T12:00:00+00:00", views=160),
        ],
        now=datetime(2026, 9, 15, 13, tzinfo=timezone.utc),
    )

    assert result["state"] == "S2_DUAL_SNAPSHOT_GROWTH"
    assert result["permissions"] == {"allow_advice": False, "allow_viral_claims": False, "allow_automated_learning": False}
    assert result["growth"]["video-1"]["metrics"]["views"] == {"baseline": 100, "current": 160, "delta": 60, "rate": 0.6}


def test_evaluator_requires_all_predecessors_before_advice():
    result = evaluate_platform_intelligence(
        platform="youtube",
        lane="real_world_ai_implementation",
        snapshots=[
            _snapshot(observed_at="2026-09-15T00:00:00+00:00", views=100),
            _snapshot(observed_at="2026-09-15T12:00:00+00:00", views=160),
        ],
        content_evidence=_content_evidence(),
        breakdown=_ready_breakdown(),
        recommendation={"reference_ids": ["video-1"], "evidence_hashes": ["a" * 64]},
        now=datetime(2026, 9, 15, 13, tzinfo=timezone.utc),
    )

    assert result["state"] == "S5_ADVISE"
    assert result["permissions"] == {"allow_advice": True, "allow_viral_claims": False, "allow_automated_learning": False}


def test_evaluator_rejects_naive_or_tampered_snapshots_fail_closed():
    bad = _snapshot(observed_at="2026-09-15T12:00:00", views=160)
    bad["raw_response_hash"] = "not-a-hash"
    result = evaluate_platform_intelligence(
        platform="youtube",
        lane="real_world_ai_implementation",
        snapshots=[_snapshot(observed_at="2026-09-15T00:00:00+00:00", views=100), bad],
        now=datetime(2026, 9, 15, 13, tzinfo=timezone.utc),
    )

    assert result["state"] == "S1_SINGLE_SNAPSHOT"
    assert "snapshot_timestamp_invalid" in result["blocking_reason_codes"]
    assert result["permissions"]["allow_advice"] is False
