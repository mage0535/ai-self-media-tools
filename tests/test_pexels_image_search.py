from pathlib import Path
from unittest.mock import patch


def test_search_images_returns_search_spec_and_candidate_score():
    from scripts.pexels_image_search import search_images

    def fake_generate(query, output, **kwargs):
        Path(output).write_bytes(b"image")
        return {
            "source_url": "https://www.pexels.com/photo/123/",
            "photographer": "Example",
            "license": "Pexels License",
        }

    with patch("scripts.pexels_image_search.load_secret", return_value="key"), patch(
        "scripts.pexels_image_search.generate_image", side_effect=fake_generate
    ):
        records = search_images("AI Excel workflow", count=1, min_width=1080, min_height=1920, include_evidence=True)

    assert len(records) == 1
    record = records[0]
    assert record["search_spec"]["version"] == "search_spec_v1"
    assert record["candidate_score"]["passed"] is True
    assert record["candidate_score"]["score"] > 0
    assert record["candidate_score"]["hard_failures"] == []


def test_search_images_filters_candidate_when_license_is_not_verified():
    from scripts.pexels_image_search import search_images

    def fake_generate(query, output, **kwargs):
        Path(output).write_bytes(b"image")
        return {
            "source_url": "https://example.invalid/asset",
            "photographer": "Unknown",
            "license": "",
            "license_verified": False,
        }

    with patch("scripts.pexels_image_search.load_secret", return_value="key"), patch(
        "scripts.pexels_image_search.generate_image", side_effect=fake_generate
    ):
        records = search_images("unmatched", count=1, include_evidence=True)

    assert records == []
