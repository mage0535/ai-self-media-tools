import json
from pathlib import Path

from PIL import Image

from content_platform.cover_quality import validate_cover


def _cover(path: Path) -> Path:
    Image.new("RGB", (1080, 1920), "navy").save(path)
    return path


def test_cover_gate_accepts_topic_specific_narrative_poster(tmp_path: Path):
    evidence = {
        "platform": "tiktok", "layout_key": "character_showdown",
        "hook": "AI notes failed?", "conflict_or_payoff": "verify three fields",
        "focal_subjects": ["cat", "dog", "checklist"],
        "content_match_reason": "the characters enact the script conflict",
        "safe_zone_verified": True, "degraded": False,
    }
    assert validate_cover(_cover(tmp_path / "cover.jpg"), evidence)["passed"] is True


def test_cover_gate_rejects_placeholder_or_degraded_cover(tmp_path: Path):
    evidence = {"platform": "tiktok", "layout_key": "screenshot_plus_caption", "degraded": True}
    result = validate_cover(_cover(tmp_path / "cover.jpg"), evidence)
    assert result["passed"] is False
    assert "viral_layout_missing" in result["failures"]
    assert "degraded_cover_forbidden" in result["failures"]
