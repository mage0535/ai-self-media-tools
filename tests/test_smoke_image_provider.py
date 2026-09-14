from pathlib import Path

from PIL import Image

from scripts.smoke_image_provider import _artifact_assessment


def test_smoke_artifact_assessment_separates_transport_from_production_quality(tmp_path: Path):
    plain = tmp_path / "plain.png"
    Image.new("RGB", (768, 768), (210, 160, 140)).save(plain)

    result = _artifact_assessment(plain, {"provider": "stock"})

    assert result["artifact_gate"]["passed"] is False
    assert result["semantic_status"] == "not_evaluated"
    assert result["production_ready"] is False


def test_smoke_artifact_assessment_blocks_provider_with_possible_branding(tmp_path: Path):
    varied = tmp_path / "varied.png"
    image = Image.new("RGB", (768, 768), "black")
    for x in range(768):
        for y in range(0, 768, 8):
            image.putpixel((x, y), ((x + y) % 255, x % 255, y % 255))
    image.save(varied)

    result = _artifact_assessment(varied, {"provider": "sense_nova", "embedded_branding_possible": True})

    assert result["branding_gate"]["passed"] is False
    assert result["production_ready"] is False
