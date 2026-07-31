import unittest

from content_platform.niche_analysis import analyze_niche
from content_platform.strategy_router import choose_content_strategy
from content_platform.viral_score import score_topic_candidate


class StrategyTests(unittest.TestCase):
    def test_niche_analysis_returns_account_and_style_signals(self):
        posts = [
            {
                "title": "3 ways to automate research",
                "body": "Start with the conclusion.\n\n1. Define the workflow\n2. Gather examples\n3. Review output\n\nSave this for later.",
                "account_handle": "example_creator",
                "platform": "xiaohongshu",
            },
            {
                "title": "How I cut 2 hours from publishing",
                "body": "Here is the checklist.\n\nUse one workflow, one review gate, one publishing queue.",
                "account_handle": "example_creator",
                "platform": "wechat",
            },
            {
                "title": "Short video script for AI workflow wins",
                "body": "Hook first. Then explain 3 steps. End with a CTA.",
                "account_handle": "video_maker",
                "platform": "douyin",
            },
        ]
        report = analyze_niche("AI workflow", posts)
        self.assertEqual(report["sample_count"], 3)
        self.assertEqual(report["account_count"], 2)
        self.assertIn("listicle", report["style_signature"]["formats"])
        self.assertIn("example_creator", report["top_accounts"])
        self.assertGreaterEqual(report["account_sample_count"]["example_creator"], 2)

    def test_viral_score_rewards_visual_hot_platform_fit(self):
        references = [{"title": "Visual automation workflow", "body": "Strong hook. Save this.", "platform": "xiaohongshu"}]
        niche_report = analyze_niche("Automation visuals", references)
        score = score_topic_candidate(
            "Automation visuals",
            {"trend_stage": "hot", "platforms": ["xiaohongshu", "douyin"], "keywords": ["automation", "visual"]},
            references,
            niche_report,
        )
        self.assertGreater(score["total_score"], 0.6)
        self.assertEqual(score["trend_stage"], "hot")
        self.assertIn("platform_fit", score["dimensions"])
        score_with_feedback = score_topic_candidate(
            "Automation visuals",
            {
                "trend_stage": "hot",
                "platforms": ["xiaohongshu", "douyin"],
                "keywords": ["automation", "visual"],
                "historical_feedback": {"platforms": {"xiaohongshu": {"views": 1000, "engagement": 120}}},
            },
            references,
            niche_report,
        )
        self.assertIn("feedback_signal", score_with_feedback["dimensions"])
        self.assertGreater(score_with_feedback["total_score"], score["total_score"])

    def test_strategy_router_selects_video_for_visual_short_video_topics(self):
        strategy = choose_content_strategy(
            "Automation visuals",
            {"platforms": ["douyin"], "audience": "operators", "keywords": ["visual", "workflow"]},
            {"total_score": 0.82, "dimensions": {"visual_promise": 0.9, "platform_fit": 0.85}, "trend_stage": "hot"},
            {"style_signature": {"formats": ["listicle", "question_hook"]}, "platform_distribution": {"douyin": 3}},
        )
        self.assertEqual(strategy["content_form"], "short_video")
        self.assertIn("douyin", strategy["primary_platforms"])
        self.assertIn("source_video", strategy["asset_plan"])
        self.assertIn("cover", strategy["asset_plan"])
        self.assertNotIn("video", strategy["asset_plan"])
        self.assertNotIn("audio", strategy["asset_plan"])
        self.assertIn("confidence", strategy)
        self.assertTrue(any("source video" in warning for warning in strategy["warnings"]))

    def test_strategy_router_selects_article_explainer_for_utility_video_platforms(self):
        strategy = choose_content_strategy(
            "AI workflow rules",
            {"platforms": ["youtube"], "keywords": ["workflow", "guide"]},
            {"total_score": 0.8, "dimensions": {"visual_promise": 0.65, "utility": 0.9}, "trend_stage": "hot"},
            {"style_signature": {"formats": ["tutorial"]}, "platform_distribution": {"youtube": 2}},
            {"viral_candidates": [{"title": "AI workflow rules", "grade": "T2"}], "topic_ammo": [{"title": "workflow guide"}]},
        )

        self.assertEqual(strategy["content_form"], "article_explainer_video")
        self.assertIn("article", strategy["asset_plan"])
        self.assertIn("knowledge_cards", strategy["asset_plan"])
        self.assertTrue(strategy["video_toolchain_plan"]["required"])
        self.assertEqual(strategy["video_toolchain_plan"]["selected_pipeline"], "article_explainer_video")
        self.assertIn("article_explainer_planner", strategy["video_toolchain_plan"]["required_tools"])

    def test_repost_source_overrides_article_explainer_selection(self):
        strategy = choose_content_strategy(
            "AI workflow source video",
            {"platforms": ["youtube"], "source_url": "https://example.com/video.mp4", "keywords": ["workflow", "guide"]},
            {"total_score": 0.8, "dimensions": {"visual_promise": 0.9, "utility": 0.9}, "trend_stage": "hot"},
            {"style_signature": {"formats": ["tutorial"]}, "platform_distribution": {"youtube": 2}},
        )

        self.assertEqual(strategy["content_form"], "short_video")
        self.assertEqual(strategy["video_toolchain_plan"]["selected_pipeline"], "localized_repost_video")


if __name__ == "__main__":
    unittest.main()
