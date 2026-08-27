import unittest

from content_platform.humanize import (
    naturalize_copy,
    repair_weak_hook,
    _burstiness_score,
    _score,
    quality_gate,
    QUALITY_TARGETS,
)


class HumanizeTests(unittest.TestCase):
    def test_naturalize_copy_returns_scores_and_rewrite_notes(self):
        result = naturalize_copy(
            "In conclusion, this solution is very important. In conclusion, you should use it.",
            {"style": {"opening_patterns": ["Lead with the payoff"], "cta": "Save this"}},
        )
        self.assertIn("body", result)
        self.assertIn("quality_scores", result)
        self.assertIn("quality_gate", result)
        self.assertIn("rewrite_notes", result)
        self.assertGreater(result["quality_scores"]["clarity"], 0)
        self.assertIn("passed", result["quality_gate"])

    def test_naturalize_copy_preserves_bare_domain(self):
        result = naturalize_copy(
            "打开 ai.kuaishou.com 注册账号。然后验证接口。最后保存配置。",
            {"style": {}, "strategy": {"content_form": "short_video"}},
        )
        self.assertIn("ai.kuaishou.com", result["body"])
        self.assertNotIn("ai.\nkuaishou", result["body"])


class BurstinessChineseTests(unittest.TestCase):
    """Chinese text burstiness: should not be depressed by lack of spaces."""

    # Long-form Chinese article with varied sentence lengths
    LONG_CN_ARTICLE = (
        "三个月下来，我的电脑上躺着 15 个 AI 工具。\n"
        "看着很硬核对吧？\n"
        "我统计了一下，这 15 个工具每天的维护成本加起来差不多 2 小时。更新、配置、权限、API key 过期——比上班还累。\n"
        "后来我做了三件事。\n"
        "第一刀：砍掉功能重叠的。我有 3 个 AI 编程助手、4 个自动化平台、2 个大模型客户端。这些工具干的事 80% 是重叠的。\n"
        "留下那个你最常用的。\n"
        "第二刀：给每个工具一个唯一的生态位。我给每个工具划了明确的边界。\n"
        "第三刀：建立准入机制。现在我要装一个新 AI 工具，必须先回答三个问题。\n"
        "你们呢？手上有多少个 AI 工具在吃灰？评论区说说。\n"
    )
    # Very uniform short sentences (low burstiness expected)
    UNIFORM_CN = "今天天气好。我去公园了。看到了很多花。花很漂亮。我很开心。然后回家了。吃了晚饭。看了电视。就睡觉了。"
    # English text with spaces (should keep original behavior)
    LONG_EN_ARTICLE = (
        "This is a very long sentence with many words to test the burstiness calculation. "
        "Short. "
        "Medium length sentence here. "
        "Another fairly long sentence with several words and phrases strung together. "
        "Tiny. "
    )

    def test_burstiness_long_chinese_article(self):
        """Chinese article with varied sentence lengths should score >= 0.45 (threshold)."""
        score = _burstiness_score(self.LONG_CN_ARTICLE)
        self.assertGreaterEqual(
            score, QUALITY_TARGETS["burstiness"],
            f"Chinese burstiness {score} below threshold {QUALITY_TARGETS['burstiness']}"
        )

    def test_burstiness_uniform_chinese_low(self):
        """Uniform short Chinese sentences should score low."""
        score = _burstiness_score(self.UNIFORM_CN)
        self.assertLess(
            score, QUALITY_TARGETS["burstiness"],
            f"Uniform Chinese burstiness {score} should be below {QUALITY_TARGETS['burstiness']}"
        )

    def test_burstiness_english_preserved(self):
        """English burstiness should remain similar to original behavior."""
        score = _burstiness_score(self.LONG_EN_ARTICLE)
        self.assertGreaterEqual(score, 0.3)

    def test_burstiness_mixed_chinese_english(self):
        """Mixed text with Chinese chars should use char-length approach."""
        mixed = (
            "ChatGPT 和 Claude 哪个好？我用了一个月。\n"
            "结论是：各有千秋。ChatGPT 写代码快，Claude 推理深。看场景选吧。\n"
        )
        score = _burstiness_score(mixed)
        self.assertGreaterEqual(score, 0.3)

    def test_burstiness_empty_or_short(self):
        """Short or empty text returns 0.3 (unchanged behavior)."""
        self.assertEqual(_burstiness_score(""), 0.3)
        self.assertEqual(_burstiness_score("你好。"), 0.3)
        self.assertEqual(_burstiness_score("A. B."), 0.3)


class HookStrengthChineseTests(unittest.TestCase):
    """Chinese hook detection should not rely solely on opening_patterns."""

    def test_hook_chinese_rhetorical_question(self):
        """Chinese rhetorical question at start should boost hook_strength."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "难道你真的需要 15 个 AI 工具吗？\n我装了又卸，卸了又装。"
        scores = _score(text, context)
        self.assertGreaterEqual(
            scores["hook_strength"], 0.60,
            f"Rhetorical question hook {scores['hook_strength']} below threshold 0.60"
        )

    def test_hook_chinese_first_person_conflict(self):
        """First-person conflict/pain point hook should boost hook_strength."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "自从开始折腾 AI 工具，我养成了一个坏习惯"
        scores = _score(text, context)
        self.assertGreaterEqual(
            scores["hook_strength"], 0.60,
            f"First-person conflict hook {scores['hook_strength']} below threshold 0.60"
        )

    def test_hook_chinese_number_lead(self):
        """Numbers at start of text should boost hook_strength."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "15 个 AI 工具，每天维护成本 2 小时。这个数字让我震惊。"
        scores = _score(text, context)
        self.assertGreaterEqual(
            scores["hook_strength"], 0.60,
            f"Number-lead hook {scores['hook_strength']} below threshold 0.60"
        )

    def test_hook_chinese_colon_conclusion(self):
        """Colon-introduced conclusion at start should boost hook_strength."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "AI 工具的最大骗局：装得越多，效率越低。"
        scores = _score(text, context)
        self.assertGreaterEqual(
            scores["hook_strength"], 0.60,
            f"Colon-conclusion hook {scores['hook_strength']} below threshold 0.60"
        )

    def test_hook_chinese_pain_point(self):
        """Pain-point keywords at start should boost hook_strength."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "踩了半年 AI 工具的坑，我学会了三件事。"
        scores = _score(text, context)
        self.assertGreaterEqual(
            scores["hook_strength"], 0.60,
            f"Pain-point hook {scores['hook_strength']} below threshold 0.60"
        )

    def test_hook_weak_text_no_boost(self):
        """Generic opening without hook signals stays at base score."""
        context = {"style": {}, "strategy": {"content_form": "long_article"}}
        text = "本文介绍了 AI 工具的基本用法。首先我们需要了解什么是 AI。"
        scores = _score(text, context)
        # Without opening_patterns or strong hook, should be <= 0.57
        self.assertLess(scores["hook_strength"], 0.60)

    def test_hook_opening_patterns_still_works(self):
        """Setting opening_patterns in context still sets 0.75 base."""
        context = {"style": {"opening_patterns": ["Lead with the payoff"]}}
        text = "Some regular text without a strong hook."
        scores = _score(text, context)
        self.assertGreaterEqual(scores["hook_strength"], 0.75)


class HookStrengthEnglishTests(unittest.TestCase):
    """English hook detection should work for international article channels."""

    def test_hook_english_conflict_payoff_passes(self):
        context = {"style": {}, "strategy": {"content_form": "long_article", "primary_platforms": ["devto"]}}
        text = "Most developers do not need another open-source AI list; they need a way to pick one tool without wasting the weekend. Here is the practical filter."
        scores = _score(text, context)
        self.assertGreaterEqual(scores["hook_strength"], 0.60)

    def test_hook_english_observed_devto_style_passes(self):
        context = {"style": {}, "strategy": {"content_form": "long_article", "primary_platforms": ["devto"]}}
        text = "Every week a new AI framework lands on GitHub. Most vanish. A few compound because they solve the real friction."
        scores = _score(text, context)
        self.assertGreaterEqual(scores["hook_strength"], 0.60)

    def test_hook_english_weak_text_no_boost(self):
        context = {"style": {}, "strategy": {"content_form": "long_article", "primary_platforms": ["devto"]}}
        text = "This article introduces several open-source tools and explains their basic features for readers."
        scores = _score(text, context)
        self.assertLess(scores["hook_strength"], 0.60)


class QualityGateG3IntegrationTests(unittest.TestCase):
    """End-to-end: naturalize_copy with Chinese content should pass G3."""

    CHINESE_ARTICLE = (
        "三个月下来，我的电脑上躺着 15 个 AI 工具。\n"
        "看着很硬核对吧？\n"
        "我统计了一下，这 15 个工具每天的维护成本加起来差不多 2 小时。更新、配置、权限、API key 过期——比上班还累。\n"
        "后来我做了三件事。\n"
        "第一刀：砍掉功能重叠的。\n"
        "第二刀：给每个工具一个唯一的生态位。\n"
        "第三刀：建立准入机制。\n"
        "你们呢？手上有多少个 AI 工具在吃灰？评论区说说。\n"
    )

    def test_naturalize_copy_chinese_passes_g3(self):
        """naturalize_copy on Chinese content should pass G3 anti-generic gate."""
        context = {
            "style": { "cta": "评论区说说" },
            "strategy": {"content_form": "long_article", "primary_platforms": ["wechat"]}
        }
        result = naturalize_copy(self.CHINESE_ARTICLE, context)
        scores = result["quality_scores"]
        gate = result["quality_gate"]
        failed = gate.get("failed_dimensions", [])

        # G3 failures should not include hook_strength or burstiness for this article
        g3_failures = [f for f in failed]
        self.assertNotIn(
            "hook_strength", g3_failures,
            f"hook_strength={scores['hook_strength']} should pass G3"
        )
        self.assertNotIn(
            "burstiness", g3_failures,
            f"burstiness={scores['burstiness']} should pass G3"
        )

    def test_repair_weak_hook_uses_title_without_new_factual_claims(self):
        context = {"style": {}, "strategy": {"content_form": "short_video"}}
        result = repair_weak_hook("快手 AI 开放平台", "这个平台整合了多种能力。\n按步骤配置即可。", context)

        self.assertTrue(result["changed"])
        self.assertTrue(result["body"].startswith("为什么快手 AI 开放平台？"))
        self.assertGreaterEqual(result["quality_scores"]["hook_strength"], 0.60)
        self.assertNotIn("数据", result["hook"])


if __name__ == "__main__":
    unittest.main()
