from content_platform.growth_policy import build_growth_strategy, validate_growth_strategy


def test_xiaohongshu_growth_strategy_contains_manual_recovery_playbook():
    strategy = build_growth_strategy(["xiaohongshu"], "image_text_note")
    playbook = strategy["xiaohongshu_growth_playbook"]

    assert validate_growth_strategy(strategy, "xiaohongshu", "image_text_note")["passed"] is True
    assert strategy["target_user_action"] == "save_or_comment"
    assert playbook["mode"] == "xiaohongshu_manual_recovery"
    assert playbook["publish_boundary"] == "manual_handoff_only_hard_gate_no_automation_ever"
    assert playbook["publishing_frequency"]["max_posts_first_7_days"] == 4
    assert playbook["publishing_frequency"]["min_gap_hours_between_posts"] == 36
    assert playbook["manual_post_publish_review"]["review_points_hours"] == [1, 24, 72]


def test_xiaohongshu_growth_strategy_rejects_automatic_or_fast_cadence_plan():
    strategy = build_growth_strategy(["xiaohongshu"], "image_text_note")
    strategy["xiaohongshu_growth_playbook"] = {
        "mode": "legacy",
        "publish_boundary": "automatic_publish",
        "publishing_frequency": {"max_posts_first_7_days": 7, "min_gap_hours_between_posts": 12},
        "manual_post_publish_review": {"review_points_hours": [24]},
    }

    result = validate_growth_strategy(strategy, "xiaohongshu", "image_text_note")

    assert result["passed"] is False
    assert "xiaohongshu_growth_playbook.recovery_mode_missing" in result["failures"]
    assert "xiaohongshu_publish_boundary.not_manual_handoff_only" in result["failures"]
    assert "xiaohongshu_frequency.recovery_cap_too_high" in result["failures"]
    assert "xiaohongshu_frequency.min_gap_too_short" in result["failures"]
    assert "xiaohongshu_review_schedule.invalid" in result["failures"]
