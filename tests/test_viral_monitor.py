import json
import tempfile
import unittest
from pathlib import Path

from content_platform.viral_monitor import account_tier, build_viral_report, score_posts_file, score_work


class ViralMonitorTests(unittest.TestCase):
    def test_account_tiers_match_growth_baselines(self):
        self.assertEqual(account_tier(500), "C")
        self.assertEqual(account_tier(20_000), "B")
        self.assertEqual(account_tier(200_000), "A")
        self.assertEqual(account_tier(2_000_000), "S")

    def test_score_work_detects_viral_candidate_against_recent_baseline(self):
        result = score_work(
            {
                "platform": "wechat",
                "title": "AI工具越用越乱",
                "views": 12000,
                "likes": 800,
                "comments": 120,
                "shares": 180,
                "saves": 260,
                "followers": 20000,
            },
            recent_metrics=[1200, 1500, 1800],
        )

        self.assertEqual(result["tier"], "B")
        self.assertIn(result["grade"], {"T1", "T2"})
        self.assertIn(result["recommendation"], {"scale_this_angle", "adapt_with_platform_specific_hook"})

    def test_build_viral_report_produces_topic_ammo(self):
        report = build_viral_report(
            [
                {"platform": "zhihu", "title": "工作流误区", "views": 9000, "likes": 400, "followers": 3000, "account": "a"},
                {"platform": "bilibili", "title": "普通作品", "views": 100, "likes": 2, "followers": 3000, "account": "b"},
            ],
            {"a": [500, 600, 700], "b": [300, 350, 400]},
        )

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(len(report["viral_candidates"]), 1)
        self.assertGreaterEqual(len(report["topic_ammo"]), 1)

    def test_score_posts_file_writes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "posts.json"
            output = root / "report.json"
            source.write_text(json.dumps({"posts": [{"title": "爆款", "views": 1000, "likes": 90, "followers": 1000}]}), encoding="utf-8")

            result = score_posts_file(source, output)

            self.assertTrue(result["ok"])
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
