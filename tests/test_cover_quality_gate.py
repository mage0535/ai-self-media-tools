import hashlib
import json
from pathlib import Path

from PIL import Image

from content_platform.cover_quality import validate_cover as canonical_validate
from scripts.cover_quality_gate import validate_cover


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(cover: Path, **updates: object) -> dict:
    payload = {
        "platform": "tiktok",
        "layout_key": "hero_conflict",
        "hook": "VERIFY FIRST",
        "title_en": "VERIFY FIRST",
        "conflict_or_payoff": "human decides",
        "focal_subjects": ["machine", "human"],
        "content_match_reason": "decision handoff",
        "cover_sha256": _sha(cover),
        "safe_zone_verified": True,
        "degraded": False,
    }
    payload.update(updates)
    return payload


def test_script_gate_delegates_to_canonical_pixel_validator(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1080, 1920), "navy").save(cover)
    evidence = tmp_path / "cover_quality_evidence.json"
    evidence.write_text(json.dumps(_evidence(cover)), encoding="utf-8")

    result = validate_cover(cover, evidence)

    assert result == canonical_validate(cover, evidence)
    assert result["passed"] is False
    assert "cover_visual_complexity_too_low" in result["failures"]
    persisted = json.loads((tmp_path / "cover_quality_gate.json").read_text(encoding="utf-8"))
    assert persisted == result


def test_cover_gate_rejects_placeholder_layout(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    Image.new("RGB", (1080, 1920), "white").save(cover)
    evidence = tmp_path / "cover_quality_evidence.json"
    evidence.write_text(
        json.dumps(_evidence(cover, layout_key="screenshot_plus_caption")), encoding="utf-8"
    )
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "viral_layout_missing" in result["failures"]
