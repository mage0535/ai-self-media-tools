import json
from pathlib import Path

from PIL import Image

from scripts.cover_quality_gate import validate_cover


def test_cover_gate_accepts_narrative_poster(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1080, 1920), "navy").save(cover)
    evidence = tmp_path / "cover_quality_evidence.json"
    evidence.write_text(json.dumps({
        "platform": "tiktok", "layout_key": "character_showdown",
        "hook": "AI says done?", "conflict_or_payoff": "dog verifies receipt",
        "focal_subjects": ["cat", "dog"], "content_match_reason": "mirrors the script conflict",
        "safe_zone_verified": True, "degraded": False,
    }), encoding="utf-8")
    assert validate_cover(cover, evidence)["passed"] is True


def test_cover_gate_rejects_placeholder_layout(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1080, 1920), "white").save(cover)
    evidence = tmp_path / "cover_quality_evidence.json"
    evidence.write_text(json.dumps({"platform": "tiktok", "layout_key": "screenshot_plus_caption"}), encoding="utf-8")
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "viral_layout_missing" in result["failures"]
