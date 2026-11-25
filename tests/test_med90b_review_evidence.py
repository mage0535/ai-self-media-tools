"""MED90-b unit tests: truthful cover/candidate provenance, XHS 3:4 <=500KB normalization, and manual-handoff layout rule."""
import hashlib
import json
import random
from pathlib import Path

from PIL import Image

from content_platform.media import MediaBridge
from content_platform.native_quality_runner import _delivery_image_layout
from content_platform.pipeline import Pipeline


def test_med90b_rendered_asset_mix_distinguishes_ai_cover_and_includes_candidates():
    assets = [
        {
            "scene_id": "cover",
            "origin": "ai_generated",
            "source_url": "generated:openai-codex",
            "cover_render_evidence": {"title_text": "test"},
            "candidate_attempts": [
                {"provider": "pexels", "origin": "real_photo", "score": 0.45, "reason": "mismatch", "kept": False},
                {"provider": "openai-codex", "origin": "ai_generated", "score": 0.85, "reason": "match", "kept": True},
            ],
        },
        {"scene_id": "section-01", "origin": "ai_generated", "source_url": "generated:openai-codex"},
    ]
    mix = Pipeline._rendered_asset_mix(assets, {"draft_meta": {}})
    assert mix["ai_edit_real_material"].startswith("not applicable")
    assert "not real_photo" in mix["ai_edit_real_material"]
    assert mix["ai_generated_with_title_overlay"] == "cover title rendered over the ai_generated background"
    assert "pexels(real_photo:score=0.45,kept=False)" in mix["real_material_retrieval"]
    assert "openai-codex(ai_generated:score=0.85,kept=True)" in mix["real_material_retrieval"]


def test_med90b_normalize_xhs_image_enforces_3_by_4_and_under_500kb(tmp_path: Path):
    # Create a noisy 1254x1254 square PNG (>1 MB) simulating gpt-image-2 output.
    rng = random.Random(42)
    img = Image.new("RGB", (1254, 1254))
    img.putdata([(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)) for _ in range(1254 * 1254)])
    p = tmp_path / "section-01.png"
    img.save(p, format="PNG")
    assert p.stat().st_size > 500_000

    MediaBridge._normalize_xhs_image(p)
    assert p.stat().st_size <= 500_000
    with Image.open(p) as out:
        assert out.format == "PNG"
        assert abs((out.width / out.height) - 0.75) < 0.01


def test_med90b_delivery_image_layout_uses_manual_handoff_for_xiaohongshu(tmp_path: Path):
    copy_p = tmp_path / "copy.txt"
    copy_p.write_text("## 实操步骤\n正文内容", encoding="utf-8")
    img_p = tmp_path / "section-01.png"
    img_p.write_bytes(b"fake-png")
    (tmp_path / "section_image_map.json").write_text(
        json.dumps([{"section": "实操步骤", "image": str(img_p)}], ensure_ascii=False), encoding="utf-8"
    )
    parts = {
        "publication_copy": [{"path": str(copy_p), "sha256": hashlib.sha256(copy_p.read_bytes()).hexdigest()}],
        "images": [{"path": str(img_p), "sha256": hashlib.sha256(img_p.read_bytes()).hexdigest()}],
    }
    xhs_layout = _delivery_image_layout(parts, platform="xiaohongshu")
    zhihu_layout = _delivery_image_layout(parts, platform="zhihu")
    assert xhs_layout["delivery_mode"] == "manual_handoff_package"
    assert "no platform draft created" in xhs_layout["rule"]
    assert zhihu_layout["delivery_mode"] == "platform_draft_insert"
    assert "platform draft is created" in zhihu_layout["rule"]
