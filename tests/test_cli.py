import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from content_platform.cli import _exec_wewrite, _load_collector_config, _load_env_defaults, execute, main, parser


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

    def test_auto_creates_an_independent_job_and_source_matrix_for_each_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = []

            class FakePipeline:
                def __init__(self, *_args):
                    pass

                def create(self, topic, platforms, brief, profile, fingerprint):
                    created.append((topic, platforms, brief))
                    return {"id": f"job-{len(created)}"}

                def run(self, job_id):
                    return {"id": job_id, "state": "blocked"}

            report = {
                "items": [{"title": "AI workflow test", "source": "github", "url": "https://example.test", "points": 20}],
                "sources": [{"source": "github", "status": "ok", "count": 1}],
            }
            with patch("content_platform.cli.Pipeline", FakePipeline), patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main([
                        "--db", str(root / "state.db"), "--config", str(root / "missing.json"), "auto", "--limit", "1",
                        "--platform", "wechat", "--platform", "xiaohongshu",
                    ])
            self.assertEqual(code, 0)
            self.assertEqual([row[1] for row in created], [["wechat"], ["xiaohongshu"]])
            self.assertEqual(created[0][2]["platform_source_matrix"]["platform"], "wechat")
            self.assertEqual(created[1][2]["platform_source_matrix"]["platform"], "xiaohongshu")

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


    def test_performance_import_and_review_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = str(root / "state.db")
            job_output = io.StringIO()
            with redirect_stdout(job_output):
                self.assertEqual(main(["--db", db, "--config", "", "create", "--topic", "metrics", "--platform", "youtube"]), 0)
            job = json.loads(job_output.getvalue())
            metrics_file = root / "metrics.json"
            metrics_file.write_text(
                json.dumps(
                    {
                        "job_id": job["id"],
                        "platform": "youtube",
                        "views": 50,
                        "likes": 1,
                        "saves": 0,
                        "follows": 0,
                        "completion_rate": 0.2,
                    }
                ),
                encoding="utf-8",
            )
            import_output = io.StringIO()
            with redirect_stdout(import_output):
                self.assertEqual(main(["--db", db, "--config", "", "performance-import", str(metrics_file)]), 0)
            review_output = io.StringIO()
            with redirect_stdout(review_output):
                self.assertEqual(main(["--db", db, "--config", "", "performance-review"]), 0)
            imported = json.loads(import_output.getvalue())
            review = json.loads(review_output.getvalue())
        self.assertEqual(imported["imported"], 1)
        self.assertIn("low_completion_rate", review["platforms"]["youtube"]["findings"])

    def test_performance_collect_cli_marks_backend_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "collect.json"
            output = io.StringIO()
            with patch("content_platform.cli._load_env_defaults", return_value=""), patch(
                "content_platform.cli._load_collector_config", return_value=({}, "")
            ), redirect_stdout(output):
                self.assertEqual(
                    main([
                        "--db",
                        str(root / "state.db"),
                        "--config",
                        "",
                        "performance-collect",
                        "--platform",
                        "wechat",
                        "--output",
                        str(output_path),
                    ]),
                    0,
                )
            result = json.loads(output.getvalue())
            self.assertEqual(result["platforms"]["wechat"]["status"], "backend_export_required")
            self.assertTrue(output_path.is_file())

    def test_performance_collect_cli_can_use_hermes_scraper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            fake_report = {"status": "ok", "platforms": {"youtube": {"status": "ok", "account_metrics": {"subscribers": 8}}}}
            with patch("content_platform.performance_collectors.collect_with_hermes_platform_scraper", return_value=fake_report) as collect:
                with redirect_stdout(output):
                    self.assertEqual(
                        main([
                            "--db",
                            str(root / "state.db"),
                            "--config",
                            "",
                            "performance-collect",
                            "--platform",
                            "youtube",
                            "--hermes-platform-scraper",
                        ]),
                        0,
                    )
            result = json.loads(output.getvalue())
        collect.assert_called_once()
        self.assertEqual(result["platforms"]["youtube"]["account_metrics"]["subscribers"], 8)

    def test_performance_source_audit_cli_writes_coverage_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "collector.json"
            out = root / "source_audit.json"
            cfg.write_text(
                json.dumps(
                    {
                        "douyin": {"state_file": "/private/douyin.json"},
                        "youtube": {"channel_url": "https://youtube.example/channel"},
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--db",
                            str(root / "state.db"),
                            "--config",
                            "",
                            "performance-source-audit",
                            "--platform",
                            "douyin",
                            "--platform",
                            "youtube",
                            "--collector-config",
                            str(cfg),
                            "--output",
                            str(out),
                        ]
                    ),
                    0,
                )
            result = json.loads(output.getvalue())
            output_exists = out.is_file()
        self.assertEqual(result["source_coverage"]["platforms"]["douyin"]["status"], "backend_only")
        self.assertEqual(result["source_coverage"]["platforms"]["youtube"]["status"], "configured")
        self.assertTrue(output_exists)

    def test_private_collector_config_is_discovered_from_runtime_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "performance-collector.json").write_text(
                json.dumps({"youtube": {"channel_url": "https://youtube.example/channel"}}),
                encoding="utf-8",
            )

            with patch("content_platform.cli.project_home", return_value=root):
                collector_config, source = _load_collector_config("")

        self.assertEqual(collector_config["youtube"]["channel_url"], "https://youtube.example/channel")
        self.assertTrue(source.endswith("performance-collector.json"))

    def test_private_proxy_env_is_loaded_without_overriding_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "proxy.env").write_text(
                "CN_PROXY=socks5://127.0.0.1:1080\nUS_PROXY=socks5://127.0.0.1:1091\n",
                encoding="utf-8",
            )

            with patch("content_platform.cli.project_home", return_value=root), patch.dict(
                os.environ,
                {"CN_PROXY": "socks5://already-set:1080"},
                # The assertion covers precedence for CN_PROXY only. A live
                # process US_PROXY must not leak into this isolated fixture.
                clear=True,
            ):
                source = _load_env_defaults()
                cn_proxy = os.environ["CN_PROXY"]
                us_proxy = os.environ["US_PROXY"]

        self.assertTrue(source.endswith("proxy.env"))
        self.assertEqual(cn_proxy, "socks5://already-set:1080")
        self.assertEqual(us_proxy, "socks5://127.0.0.1:1091")

    def test_performance_source_audit_uses_default_private_collector_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "performance-collector.json").write_text(
                json.dumps({"youtube": {"channel_url": "https://youtube.example/channel"}}),
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch("content_platform.cli.project_home", return_value=root), redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--db",
                            str(root / "state.db"),
                            "--config",
                            "",
                            "performance-source-audit",
                            "--platform",
                            "youtube",
                        ]
                    ),
                    0,
                )
            result = json.loads(output.getvalue())

        self.assertEqual(result["source_coverage"]["platforms"]["youtube"]["status"], "configured")


if __name__ == "__main__":
    unittest.main()
