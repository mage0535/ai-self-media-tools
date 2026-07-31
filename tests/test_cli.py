import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from content_platform.cli import _exec_wewrite, execute, main, parser


class CliTests(unittest.TestCase):
    def test_demo_outputs_published_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", db, "--config", str(Path(tmp) / "missing.json"), "demo"])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["deliveries"][0]["status"], "drafted")

    def test_health_initializes_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", db, "--config", "", "health"])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])

    def test_publish_matrix_live_mode_is_blocked_from_direct_publishers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix"
            (matrix / "copy").mkdir(parents=True)
            (matrix / "copy" / "post.md").write_text("# Title\n\nBody", encoding="utf-8")
            args = parser().parse_args(["--db", str(root / "state.db"), "--config", "", "publish-matrix", "--matrix", str(matrix), "--platform", "devto"])
            with patch("content_platform.publishers.build_publisher") as build:
                result = execute(args)
        build.assert_not_called()
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["results"][0]["status"], "blocked")



    def test_wewrite_cli_uses_visual_prompts(self):
        args = SimpleNamespace(action="article", topic="测试选题", output="")
        fake = SimpleNamespace(returncode=0, stdout='{"run_id":"run_1"}', stderr="")
        with patch("content_platform.cli.os.path.exists", return_value=True), patch("subprocess.run", return_value=fake) as run:
            result = _exec_wewrite(args, {})
        self.assertTrue(result["ok"])
        command = run.call_args[0][0]
        self.assertIn("--visual-mode", command)
        self.assertIn("prompts", command)
        self.assertIn("--max-images", command)
        self.assertNotIn("none", command)

    def test_auto_does_not_mark_blocked_topic_as_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.json"
            cfg.write_text(json.dumps({"trends": {"fallback_enabled": True, "fallback_keywords": ["AI workflow"]}, "feature_flags": {"channel_auto_workflow_gate": "enforce"}, "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"}}), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", str(root / "state.db"), "--config", str(cfg), "auto", "--limit", "1", "--platform", "devto", "--refresh"])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result[0]["state"], "blocked")
            from content_platform.store import Store
            self.assertEqual(Store(root / "state.db").used_topics("devto"), set())

    def test_analyze_topic_returns_strategy_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--db",
                        db,
                        "--config",
                        "",
                        "analyze-topic",
                        "--topic",
                        "Automation visuals",
                        "--brief",
                        '{"platforms":["douyin"],"reference_posts":[{"title":"Hook","body":"1. A\\n2. B\\nSave this.","account_handle":"example_creator"}]}',
                    ]
                )
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["strategy"]["content_form"], "short_video")

    def test_account_report_summarizes_reference_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--db",
                        db,
                        "--config",
                        "",
                        "account-report",
                        "--topic",
                        "Automation visuals",
                        "--brief",
                        '{"reference_posts":[{"title":"Hook","body":"1. A 2. B Save this.","account_handle":"example_creator","platform":"xiaohongshu"}]}',
                    ]
                )
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["account_count"], 1)
        self.assertIn("example_creator", result["top_accounts"])

    def test_article_video_cli_writes_explainer_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article = root / "article.md"
            article.write_text("# AI工具使用规则\n\n先讲问题，再讲方法，最后给行动。", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", str(root / "state.db"), "--config", "", "article-video", "--input", str(article), "--output-dir", str(root / "video")])
            result = json.loads(output.getvalue())
            plan_exists = Path(result["video_toolchain_plan"]).is_file()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_pipeline"], "article_explainer_video")
        self.assertTrue(plan_exists)

    def test_viral_monitor_cli_scores_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "posts.json"
            source.write_text(json.dumps({"posts": [{"title": "AI工作流爆款", "views": 5000, "likes": 500, "followers": 5000}]}), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", str(root / "state.db"), "--config", "", "viral-monitor", "--input", str(source)])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)


if __name__ == "__main__":
    unittest.main()
