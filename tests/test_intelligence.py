import unittest
import json
import tempfile
from pathlib import Path

from content_platform.compliance import ComplianceChecker
from content_platform.intelligence import analyze_reference_posts, build_generation_context, collect_reference_posts
from content_platform.trends import rank_trends


class IntelligenceTests(unittest.TestCase):
    def test_trend_ranking_uses_fit_history_and_source_diversity(self):
        items = [
            {"title": "AI agent release", "source": "hn", "points": 100},
            {"title": "AI-agent release!", "source": "hn", "points": 90},
            {"title": "Agent operations guide", "source": "techcrunch", "points": 5},
            {"title": "Celebrity news", "source": "other", "points": 500},
        ]
        profile = {"keywords": ["AI", "agent"], "source_weights": {"hn": 3, "techcrunch": 2}}
        ranked = rank_trends(items, profile, used={"ai agent release"}, limit=2)
        self.assertEqual(ranked[0]["title"], "Agent operations guide")
        self.assertNotIn("Celebrity news", [item["title"] for item in ranked])
        self.assertIn(ranked[0]["trend_stage"], {"hot", "emerging", "viral_candidate"})

    def test_reference_post_analysis_extracts_style_signals(self):
        posts = [
            {
                "title": "3 个 AI 自动化误区，很多人一开始就踩坑",
                "body": "先说结论：不要一上来堆工具。\n\n1. 先定目标\n2. 再做闭环\n3. 最后扩平台\n\n你踩过哪个坑？评论区聊聊。",
            },
            {
                "title": "我用一套工作流省下 2 小时/天",
                "body": "开头先抛结果，再讲步骤，最后给清单。\n\n建议收藏，照着做。",
            },
        ]
        style = analyze_reference_posts(posts)
        self.assertEqual(style["sample_count"], 2)
        self.assertIn("listicle", style["formats"])
        self.assertTrue(style["cta"])

    def test_reference_posts_fall_back_to_same_track_trend_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trending_2026-07-02.json").write_text(
                json.dumps(
                    {
                        "trends": [
                            {"title": "AI 自动化工作流", "source": "hn", "url": "https://example.com/ai"},
                            {"title": "娱乐热点", "source": "hn", "url": "https://example.com/fun"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with unittest.mock.patch("content_platform.intelligence._fetch_url", return_value="<title>AI 自动化工作流</title><p>建议收藏。1. 先定目标</p>"):
                posts = collect_reference_posts({"keywords": ["AI"], "trend_cache_dir": str(root)}, limit=2)
        self.assertEqual(len(posts), 1)
        self.assertIn("AI 自动化工作流", posts[0]["title"])

    def test_numeric_claim_without_source_requires_review(self):
        result = ComplianceChecker().evaluate("Efficiency improved by 73% in 2026.", {"sources": []}, ["wechat"])
        self.assertEqual(result["level"], "review")
        self.assertIn("numeric_claim_without_source", [finding["code"] for finding in result["findings"]])

    def test_numeric_claim_with_source_passes_claim_check(self):
        result = ComplianceChecker().evaluate(
            "Efficiency improved by 73% in 2026.", {"sources": ["https://example.com/report"]}, ["wechat"]
        )
        self.assertNotIn("numeric_claim_without_source", [finding["code"] for finding in result["findings"]])

    def test_generation_context_includes_niche_score_and_strategy(self):
        context = build_generation_context(
            "Automation visuals",
            {
                "trend_stage": "hot",
                "platforms": ["douyin", "xiaohongshu"],
                "reference_posts": [{"title": "Hook first", "body": "1. Step one\n2. Step two\nSave this.", "account_handle": "example_creator", "platform": "xiaohongshu"}],
            },
        )
        self.assertIn("niche_report", context)
        self.assertIn("viral_score", context)
        self.assertIn("strategy", context)
        self.assertIn("topic_clusters", context)
        self.assertEqual(context["strategy"]["content_form"], "short_video")


if __name__ == "__main__":
    unittest.main()
