import json

import pytest

from content_platform.video_preflight import VideoPreflightError, validate_video_preflight


def _payload():
    return {
        "platform": "douyin_pet",
        "research_pack": {"attempted_sources": 5, "successful_sources": 3, "degraded_source": True},
        "topic_selection": {"selected": True, "reason": "platform-specific evidence"},
        "content_brief": {"hook": "猫咪行为观察"},
        "asset_plan": {"source": "fresh_generated_assets"},
        "quality_gates": {"allow_render": True},
    }


def test_preflight_blocks_degraded_research_by_default(tmp_path):
    (tmp_path / "video_preflight.json").write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(VideoPreflightError, match="research_native_evidence_required"):
        validate_video_preflight(tmp_path, "douyin_pet")


def test_preflight_accepts_degraded_research_only_with_explicit_override(tmp_path):
    payload = _payload()
    payload["allow_degraded_render"] = True
    (tmp_path / "video_preflight.json").write_text(json.dumps(payload), encoding="utf-8")
    assert validate_video_preflight(tmp_path, "douyin_pet")["platform"] == "douyin_pet"


def test_preflight_blocks_missing_research(tmp_path):
    with pytest.raises(VideoPreflightError, match="video_preflight.json missing"):
        validate_video_preflight(tmp_path, "douyin_pet")


def test_preflight_blocks_weak_sources_and_uncommitted_topic(tmp_path):
    payload = _payload()
    payload["research_pack"]["attempted_sources"] = 2
    payload["topic_selection"]["selected"] = False
    (tmp_path / "video_preflight.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VideoPreflightError, match="below_5.*topic_selection_not_committed"):
        validate_video_preflight(tmp_path, "douyin_pet")