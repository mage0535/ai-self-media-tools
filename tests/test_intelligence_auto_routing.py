import unittest

from content_platform.intelligence import build_generation_context


class IntelligenceAutoRoutingTests(unittest.TestCase):
    def test_generation_context_uses_viral_monitor_and_selects_explainer_video(self):
        context = build_generation_context(
            "AI workflow rules",
            {
                "platforms": ["youtube"],
                "keywords": ["workflow", "guide"],
                "reference_posts": [
                    {
                        "platform": "youtube",
                        "account_handle": "creator_a",
                        "title": "AI workflow guide",
                        "body": "A practical tutorial with steps and a checklist.",
                        "views": 12000,
                        "likes": 900,
                        "comments": 120,
                        "shares": 80,
                        "followers": 20000,
                    }
                ],
                "recent_by_account": {"creator_a": [1500, 1800, 2000]},
            },
        )

        self.assertIn("viral_growth_report", context)
        self.assertGreaterEqual(len(context["viral_growth_report"]["viral_candidates"]), 1)
        self.assertEqual(context["strategy"]["content_form"], "article_explainer_video")
        self.assertEqual(context["strategy"]["video_toolchain_plan"]["selected_pipeline"], "article_explainer_video")


if __name__ == "__main__":
    unittest.main()
