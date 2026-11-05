from content_platform.media_quality import (_article_background_gate, _real_scene_background_gate,
                                            _section_real_scene_mapping_gate, _article_backgrounds)
from tests.test_media_quality import complete_real_scene_background_plan


def _generated(i, **extra):
    """What pipeline._rendered_background writes for an AI section image (MED28)."""
    return {"asset_id": f"/r/section-0{i}.png", "path": f"/r/section-0{i}.png", "section": f"section-{i}",
            "asset_type": "generated_image", "real_scene": False, "rights_cleared": False, "license": "",
            "source": f"go_gemini:prompt-{i}", "source_url": f"go_gemini:prompt-{i}", "match_reason": "matches the section",
            "semantic_match_score": 0.81, **extra}


def _packet(rows):
    plan = complete_real_scene_background_plan(3)
    plan.pop("per_slide_backgrounds")
    plan["backgrounds"] = rows
    return {"real_scene_background_plan": plan}


def test_article_accepts_declared_generated_illustrations_and_real_photos():
    real = complete_real_scene_background_plan(1)["per_slide_backgrounds"]
    packet = _packet(real + [_generated(2), _generated(3)])
    gate = _article_background_gate(packet)
    assert gate["passed"] is True and gate["generated_illustrations"] == 2
    # Xiaohongshu cards and video scenes keep the strict real-background rule.
    assert _real_scene_background_gate(packet)["passed"] is False
    mapping = [{"section": "problem"}, {"section": "section-2"}, {"section": "section-3"}]
    assert _section_real_scene_mapping_gate(packet, mapping, backgrounds=_article_backgrounds(packet))["passed"] is True
    assert _section_real_scene_mapping_gate(packet, mapping)["passed"] is False


def test_article_rejects_weak_undeclared_or_card_backgrounds():
    for bad in (_generated(3, semantic_match_score=0.6), _generated(3, rights_cleared=True),
                _generated(3, source_url=""), _generated(3, asset_type="design_card")):
        assert _article_background_gate(_packet([_generated(1), _generated(2), bad]))["passed"] is False
    assert _article_background_gate(_packet([_generated(1), _generated(2)]))["passed"] is False  # minimum 3
