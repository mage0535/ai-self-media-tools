"""Zhihu growth policy recovery checks."""

from content_platform.growth_policy import build_growth_strategy, validate_growth_strategy


def test_zhihu_growth_strategy_carries_similarity_recovery_playbook():
    plan = build_growth_strategy(["zhihu"], "article", {"platforms": {"zhihu": {"views": 10}}})

    assert plan["platform"] == "zhihu"
    assert "pin_not_article_excerpt" in plan["platform_growth_rules"]
    assert plan["zhihu_growth_playbook"]["mode"] == "zhihu_similarity_recovery"
    assert plan["zhihu_growth_playbook"]["anti_spam_similarity"]["lookback_days"] >= 14


def test_zhihu_growth_strategy_validation_requires_strict_pin_policy():
    plan = build_growth_strategy(["zhihu"], "article", {"platforms": {"zhihu": {"views": 10}}})

    result = validate_growth_strategy(plan, "zhihu", "article")

    assert result["passed"] is True


def test_zhihu_growth_strategy_validation_rejects_loose_overlap():
    plan = build_growth_strategy(["zhihu"], "article", {"platforms": {"zhihu": {"views": 10}}})
    plan["zhihu_growth_playbook"]["anti_spam_similarity"]["max_pin_article_overlap"] = 0.8

    result = validate_growth_strategy(plan, "zhihu", "article")

    assert result["passed"] is False
    assert "zhihu_pin_overlap_threshold.too_loose" in result["failures"]
