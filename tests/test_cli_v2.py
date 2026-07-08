import io
import json
import tempfile
import unittest
from contextlib import chdir
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from content_platform.cli import main


class CliV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = str(self.root / "state.db")
        self.config = str(self.root / "missing.json")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["--db", self.db, "--config", self.config, *args])
        payload = json.loads(output.getvalue() or error.getvalue())
        return code, payload

    def test_signed_review_action_approves_reviewed_job(self):
        _, created = self.call("create", "--topic", "topic", "--platform", "wechat", "--profile", "default")
        self.call("run", created["id"])
        _, token = self.call("review-token", created["id"], "--action", "approve")
        code, approved = self.call("review-action", token["token"], "--action", "approve", "--actor", "reviewer")
        self.assertEqual(code, 0)
        self.assertEqual(approved["state"], "approved")
        replay_code, replay = self.call("review-action", token["token"], "--action", "approve", "--actor", "reviewer")
        self.assertEqual(replay_code, 2)
        self.assertIn("review_required", replay["error"])

    def test_metrics_and_performance_commands(self):
        _, created = self.call("create", "--topic", "topic", "--platform", "wechat")
        code, recorded = self.call(
            "record-performance", created["id"], "--platform", "wechat", "--views", "10", "--likes", "2"
        )
        self.assertEqual(code, 0)
        self.assertEqual(recorded["views"], 10)
        output = self.root / "metrics.prom"
        code, metrics = self.call("metrics", "--output", str(output))
        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        self.assertGreater(metrics["bytes"], 0)

    def test_recover_command_reports_stale_jobs(self):
        code, result = self.call("recover")
        self.assertEqual(code, 0)
        self.assertEqual(result["recovered"], 0)

    def test_task_market_scan_command_returns_summary(self):
        fake_result = {
            "env": "cn",
            "summary": {"total": 2, "eligible": 1, "manual": 1, "blocked": 0},
            "tasks": [{"task_id": "a"}, {"task_id": "b"}],
        }
        with patch("content_platform.task_market.TaskMarketRunner.scan", return_value=fake_result):
            code, result = self.call("task-market-scan", "--env", "cn")
        self.assertEqual(code, 0)
        self.assertEqual(result["summary"]["eligible"], 1)

    def test_task_market_auto_command_executes_runner(self):
        fake_result = {"accepted": 1, "completed": 1, "manual": 0, "failed": 0}
        with patch("content_platform.task_market.TaskMarketRunner.auto_run", return_value=fake_result):
            code, result = self.call("task-market-auto", "--env", "cn")
        self.assertEqual(code, 0)
        self.assertEqual(result["completed"], 1)

    def test_delivery_readiness_command_returns_tool_summary(self):
        fake_result = {"publishers": {"wechat": {"type": "wechat-draft"}}, "tools": {"social_auto_upload": {"project_dir_exists": True}}}
        with patch("content_platform.cli.inspect_delivery_readiness", return_value=fake_result):
            code, result = self.call("delivery-readiness")
        self.assertEqual(code, 0)
        self.assertTrue(result["tools"]["social_auto_upload"]["project_dir_exists"])

    def test_content_readiness_command_returns_registry_summary(self):
        fake_result = {"tools": {"content_tools": {"ffmpeg": {"available": True}}}}
        with patch("content_platform.cli.inspect_delivery_readiness", return_value=fake_result):
            code, result = self.call("content-readiness")
        self.assertEqual(code, 0)
        self.assertTrue(result["tools"]["content_tools"]["ffmpeg"]["available"])

    def test_feedback_summary_command_returns_aggregated_metrics(self):
        _, created = self.call("create", "--topic", "topic", "--platform", "wechat")
        self.call("record-performance", created["id"], "--platform", "wechat", "--views", "100", "--likes", "12", "--comments", "3", "--shares", "2")
        code, result = self.call("feedback-summary")
        self.assertEqual(code, 0)
        self.assertEqual(result["platforms"]["wechat"]["views"], 100)

    def test_project_audit_command_reports_clean_repo(self):
        with chdir(self.root):
            code, result = self.call("project-audit")
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIn("scanned_files", result)

    def test_task_market_auto_without_key_returns_clean_skip_result(self):
        code, result = self.call("task-market-auto", "--env", "cn")
        self.assertEqual(code, 0)
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertIn("reason", result)

    def test_generation_worker_exits_cleanly_when_no_jobs(self):
        code, result = self.call("generation-worker", "--poll-interval", "1", "--batch-size", "1", "--once")
        self.assertEqual(code, 0)
        self.assertIn("processed", result)


if __name__ == "__main__":
    unittest.main()
