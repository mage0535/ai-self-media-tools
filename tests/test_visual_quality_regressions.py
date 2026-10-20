from content_platform.video_recipe import recipe_core_fingerprint


def _recipe(signatures):
    return {
        "selected_pipeline": "explainer_video",
        "content_form": "original_short_video",
        "template_family": "content_driven_explainer_v1",
        "modules": ["template_theme", "cinema_composition_layout", "shotcraft_motion_css"],
        "style_variants": {
            "color_mood": "dark_blue",
            "motion_density": "medium",
            "text_layout": "headline_plus_lower_third",
            "scene_change_interval_sec": 4,
        },
        "asset_strategy": {"primary": "verified_visual_assets", "fallback": "none", "forbidden": []},
        "dom_structure_signatures": signatures,
    }


def test_recipe_core_fingerprint_includes_final_dom_structure_sequence():
    first = _recipe(["factory_scene", "annotated_defect", "human_review"])
    second = _recipe(["title_card", "title_card", "title_card"])

    assert recipe_core_fingerprint(first) != recipe_core_fingerprint(second)


def test_recipe_core_fingerprint_ignores_decorative_color_and_title_variants():
    first = _recipe(["factory_scene", "annotated_defect", "human_review"])
    second = _recipe(["factory_scene", "annotated_defect", "human_review"])
    first["title"] = "First headline"
    second["title"] = "Completely different headline"
    first["style_variants"]["color_mood"] = "dark_blue"
    second["style_variants"]["color_mood"] = "warm_orange"
    first["style_variants"]["recipe_variant"] = "title-derived-a"
    second["style_variants"]["recipe_variant"] = "title-derived-b"

    assert recipe_core_fingerprint(first) == recipe_core_fingerprint(second)


def test_recipe_core_fingerprint_includes_scene_contract_structure_sequence():
    first = _recipe([])
    second = _recipe([])
    first["scene_contract_sequence"] = [
        {"visual_mode": "factory_scene", "group_motion": ["focus_shift"]},
        {"visual_mode": "annotated_defect", "group_motion": ["callout_draw"]},
    ]
    second["scene_contract_sequence"] = [
        {"visual_mode": "title_card", "group_motion": ["fade"]},
        {"visual_mode": "title_card", "group_motion": ["fade"]},
    ]

    assert recipe_core_fingerprint(first) != recipe_core_fingerprint(second)


def test_recipe_core_fingerprint_accepts_raw_scene_contract_sequence():
    first = _recipe([])
    second = _recipe([])
    first["scene_contract"] = [{"visual_mode": "factory_scene"}]
    second["scene_contract"] = [{"visual_mode": "title_card"}]

    assert recipe_core_fingerprint(first) != recipe_core_fingerprint(second)