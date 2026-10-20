import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import content_platform.cover_quality as cover_quality
from content_platform.cover_quality import validate_cover


ATTEMPT15 = Path(
    "data/runs/douyin_ai/20260917_industrial_inspection_r1/render_attempt15"
)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(path: Path, title: str = "VERIFY FIRST", **updates: object) -> dict:
    background = path.with_name("background.png")
    if not background.exists():
        Image.new("RGB", (320, 568), "#18384f").save(background)
    evidence = {
        "platform": "tiktok",
        "layout_key": "hero_conflict",
        "hook": title,
        "title_en": title,
        "conflict_or_payoff": "route uncertainty to a human",
        "focal_subjects": ["machine", "human"],
        "content_match_reason": "the cover shows the decision handoff",
        "background_provenance": {
            "path": str(background),
            "source": "test_fixture",
            "visible_required": True,
        },
        "renderer": "test_fixture",
        "independent_render": True,
        "cover_sha256": _sha256(path),
        # Legacy self-attestation must not satisfy the pixel gate.
        "safe_zone_verified": True,
        "degraded": False,
    }
    evidence.update(updates)
    return evidence


def _solid_cover(path: Path) -> Path:
    Image.new("RGB", (1080, 1920), "navy").save(path)
    return path


def _poster(path: Path, *, duplicate_title: bool = False, title_y: int = 260) -> Path:
    image = Image.new("RGB", (1080, 1920), "#071421")
    draw = ImageDraw.Draw(image)
    # Give the pixel analyzer real tonal, edge, and spatial structure.
    for y in range(0, 1920, 48):
        color = (8 + (y // 48) % 22, 30 + (y // 64) % 35, 45 + (y // 32) % 45)
        draw.rectangle((0, y, 1080, min(1919, y + 47)), fill=color)
    draw.ellipse((650, 500, 940, 790), fill="#ef8354", outline="white", width=12)
    draw.rectangle((90, 900, 490, 1210), fill="#123a52", outline="#63d7ff", width=10)
    draw.rectangle((590, 900, 990, 1210), fill="#203f35", outline="#82f6b1", width=10)
    title_font = ImageFont.truetype(FONT, 88)
    body_font = ImageFont.truetype(FONT, 42)
    draw.text((90, title_y), "VERIFY FIRST", font=title_font, fill="white")
    draw.text((110, 980), "MACHINE FLAGS", font=body_font, fill="white")
    draw.text((625, 980), "HUMAN DECIDES", font=body_font, fill="white")
    if duplicate_title:
        draw.text((90, 1500), "VERIFY FIRST", font=title_font, fill="#b6bcc2")
    image.save(path)
    return path


def test_cover_gate_rejects_evidence_only_solid_color_poster(tmp_path: Path):
    cover = _solid_cover(tmp_path / "cover.png")
    result = validate_cover(cover, _evidence(cover))
    assert result["passed"] is False
    assert result["status"] == "fail"
    assert "cover_visual_complexity_too_low" in result["failures"]
    assert result["pixel_metrics"]["edge_density"] == 0.0


def test_cover_gate_rejects_missing_background_provenance(tmp_path: Path):
    cover = _poster(tmp_path / "cover.png")
    result = validate_cover(cover, _evidence(cover, background_provenance=None))
    assert result["passed"] is False
    assert "background_provenance_missing" in result["failures"]


def test_cover_gate_binds_evidence_to_exact_cover_sha(tmp_path: Path):
    cover = _poster(tmp_path / "cover.png")
    evidence = _evidence(cover, cover_sha256="0" * 64)
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "cover_sha256_mismatch" in result["failures"]
    assert result["cover_sha256"] == _sha256(cover)


def test_cover_gate_uses_machine_safe_zone_geometry_not_boolean(tmp_path: Path):
    cover = _poster(tmp_path / "cover.png", title_y=2)
    result = validate_cover(cover, _evidence(cover))
    assert result["passed"] is False
    assert "title_outside_safe_zone" in result["failures"]
    assert result["safe_zone"]["source"] == "ocr_geometry"
    assert result["safe_zone"]["title_boxes"]


def test_cover_gate_rejects_duplicate_or_background_residual_title(tmp_path: Path):
    cover = _poster(tmp_path / "cover.png", duplicate_title=True)
    result = validate_cover(cover, _evidence(cover))
    assert result["passed"] is False
    assert "duplicate_or_background_text" in result["failures"]


def test_low_ocr_confidence_requires_review_instead_of_passing(tmp_path: Path, monkeypatch):
    cover = _poster(tmp_path / "cover.png")

    def low_confidence_ocr(*_args, **_kwargs):
        return {
            "available": True,
            "words": [
                {"text": "VERIFY", "confidence": 18.0, "left": 100, "top": 300, "width": 200, "height": 80, "block": 1, "line": 1},
                {"text": "FIRST", "confidence": 20.0, "left": 320, "top": 300, "width": 180, "height": 80, "block": 1, "line": 1},
            ],
            "error": "",
        }

    monkeypatch.setattr(cover_quality, "_run_ocr", low_confidence_ocr)
    result = validate_cover(cover, _evidence(cover))
    assert result["passed"] is False
    assert result["status"] == "review_required"
    assert "ocr_confidence_low" in result["review_reasons"]


def test_script_validator_is_the_canonical_validator(tmp_path: Path):
    from scripts.cover_quality_gate import validate_cover as script_validate

    cover = _solid_cover(tmp_path / "cover.png")
    evidence_path = tmp_path / "cover_quality_evidence.json"
    evidence_path.write_text(json.dumps(_evidence(cover)), encoding="utf-8")
    assert script_validate(cover, evidence_path) == validate_cover(cover, evidence_path)


def test_media_evidence_writer_binds_generated_cover_sha(tmp_path: Path):
    from content_platform.media import MediaBridge

    cover = _poster(tmp_path / "cover.png")
    job = {
        "topic": "human review",
        "platforms": ["tiktok"],
        "draft_meta": {"cover_design": {
            "layout_key": "hero_conflict",
            "hook": "VERIFY FIRST",
            "conflict_or_payoff": "human decides",
            "focal_subjects": ["machine", "human"],
            "content_match_reason": "decision handoff",
        }},
    }
    MediaBridge._persist_asset_provenance(
        tmp_path,
        [{"role": "cover", "path": str(cover)}],
        [{"purpose": "cover"}],
        "test-provider",
        job,
    )
    evidence = json.loads((tmp_path / "cover_quality_evidence.json").read_text(encoding="utf-8"))
    assert evidence["cover_sha256"] == _sha256(cover)
    assert evidence["title"] == "VERIFY FIRST"


def test_current_render_attempt15_cover_is_blocked():
    result = validate_cover(ATTEMPT15 / "cover.png", ATTEMPT15 / "cover_evidence.json")
    assert result["passed"] is False
    assert result["status"] == "fail"
    assert set(result["failures"]) & {
        "cover_visual_complexity_too_high",
        "text_block_count_too_high",
        "information_module_count_too_high",
        "competing_focal_points",
        "duplicate_or_background_text",
    }


def test_cover_gate_rejects_placeholder_or_degraded_cover(tmp_path: Path):
    cover = _solid_cover(tmp_path / "cover.png")
    evidence = _evidence(cover, layout_key="screenshot_plus_caption", degraded=True)
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "viral_layout_missing" in result["failures"]
    assert "degraded_cover_forbidden" in result["failures"]


def test_cover_generator_omits_empty_secondary_focal_points():
    from scripts.gen_cover import _optional_cover_markup

    markup = _optional_cover_markup(tag="", hook="", cta="", badge="")
    assert markup == {"tag": "", "hook": "", "cta": ""}

    markup = _optional_cover_markup(
        tag="AI效率实测", hook="先收藏", cta="每日一个案例", badge="关注"
    )
    assert "AI效率实测" in markup["tag"]
    assert "先收藏" in markup["hook"]
    assert "每日一个案例" in markup["cta"]
    assert "关注" in markup["cta"]


def test_cover_gate_rejects_background_crushed_to_solid(tmp_path: Path):
    image = Image.new("RGB", (1080, 1920), "#0a121e")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(FONT, 72)
    draw.text((100, 200), "VERIFY FIRST", font=title_font, fill="white")
    cover = tmp_path / "cover.png"
    image.save(cover)

    evidence = _evidence(cover)
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "background_crushed_to_solid" in result["failures"]


def test_cover_gate_rejects_heavy_overlay_suppression(tmp_path: Path):
    bg = Image.new("RGB", (1080, 1920), "#ffffff")
    bg_path = tmp_path / "bright_bg.png"
    bg.save(bg_path)

    image = Image.new("RGB", (1080, 1920), "#101010")
    cover = tmp_path / "cover.png"
    image.save(cover)

    evidence = _evidence(cover, background_provenance={"path": str(bg_path), "source": "fixture", "visible_required": True})
    result = validate_cover(cover, evidence)
    assert result["passed"] is False
    assert "heavy_overlay_suppressed_background" in result["failures"]
