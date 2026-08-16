import io
import json
import tempfile
import unittest
from contextlib import chdir
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from content_platform.cli import main
from content_platform.store import Store


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

    def test_record_manual_publication_creates_global_topic_receipt(self):
        code, receipt = self.call(
            "record-manual-publication",
            "--platform", "kuaishou",
            "--topic", "A practical AI workflow",
            "--topic-fingerprint", "ai-workflow-practical",
            "--external-id", "platform:123",
        )

        self.assertEqual(code, 0)
        self.assertEqual(receipt["status"], "published")
        self.assertIn("ai-workflow-practical", Store(self.db).used_topics(lookback_days=7))

    def test_overnight_plan_command_writes_a_recoverable_serial_plan(self):
        tasks = self.root / "tasks.json"
        output = self.root / "plan.json"
        tasks.write_text(json.dumps([
            {"platform": "wechat", "topic": "topic", "stage": "article", "estimate_minutes": 15},
        ]), encoding="utf-8")
        code, result = self.call("overnight-plan", "--tasks", str(tasks), "--output", str(output))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["tasks"][0]["platform"], "wechat")

    def test_overnight_prepare_writes_one_independent_task_per_due_slot(self):
        slots = self.root / "slots.json"
        output = self.root / "prepared.json"
        slots.write_text(json.dumps([{"platform": "wechat", "estimate_minutes": 15}]), encoding="utf-8")
        Store(self.db).save_tool_inventory("growth_strategy:wechat:latest", {"policy_id": "growth_quality_policy_v1"})
        report = {
            "items": [{"title": "AI workflow", "source": "github", "points": 10, "url": "https://example.test"}],
            "sources": [{"source": "github", "status": "ok", "count": 1}],
            "summary": {"items": 1},
        }
        with patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
            code, result = self.call("overnight-prepare", "--slots", str(slots), "--output", str(output), "--weekday", "3")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "prepared")
        task = json.loads(output.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(task["platform"], "wechat")
        self.assertEqual(task["topic"], "AI workflow")

    def test_overnight_prepare_blocks_due_slot_without_growth_strategy_snapshot(self):
        slots = self.root / "slots.json"
        output = self.root / "prepared.json"
        slots.write_text(json.dumps([{"platform": "zhihu", "estimate_minutes": 15}]), encoding="utf-8")
        report = {
            "items": [{"title": "AI workflow", "source": "github", "points": 10, "url": "https://example.test"}],
            "sources": [{"source": "github", "status": "ok", "count": 1}],
            "summary": {"items": 1},
        }
        with patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
            code, result = self.call("overnight-prepare", "--slots", str(slots), "--output", str(output))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "prepared")
        task = json.loads(output.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(task["state"], "blocked")
        self.assertEqual(task["reason"], "growth strategy snapshot missing")

    def test_overnight_prepare_shadows_missing_real_platform_evidence_before_enforcement(self):
        slots = self.root / "slots.json"
        output = self.root / "prepared.json"
        config = self.root / "config.json"
        slots.write_text(json.dumps([{"platform": "zhihu", "estimate_minutes": 15}]), encoding="utf-8")
        config.write_text(json.dumps({"feature_flags": {"real_platform_trend_evidence_mode": "shadow"}}), encoding="utf-8")
        Store(self.db).save_tool_inventory("growth_strategy:zhihu:latest", {"policy_id": "growth_quality_policy_v1"})
        report = {
            "items": [{"title": "AI workflow", "source": "github", "points": 10, "url": "https://example.test"}],
            "sources": [{"source": "github", "status": "ok", "count": 1}],
            "summary": {"items": 1},
        }
        self.config = str(config)
        with patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
            code, _ = self.call("overnight-prepare", "--slots", str(slots), "--output", str(output))

        self.assertEqual(code, 0)
        task = json.loads(output.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(task["state"], "ready_for_plan")
        self.assertEqual(task["trend_evidence_gate"]["mode"], "shadow")
        self.assertFalse(task["trend_evidence_gate"]["passed"])

    def test_overnight_sync_state_reconciles_existing_job_without_replaying_work(self):
        job = Store(self.db).create_job("topic", ["wechat"])
        state = self.root / "state.json"
        state.write_text(json.dumps({"status": "partial", "tasks": [{"platform": "wechat", "job_id": job["id"], "state": "failed"}]}), encoding="utf-8")
        output = self.root / "acceptance_summary.json"

        code, result = self.call("overnight-sync-state", "--state", str(state), "--output", str(output))

        self.assertEqual(code, 0)
        self.assertEqual(result["platforms"][0]["state"], "created")
        self.assertTrue(output.is_file())

    def test_overnight_acceptance_command_writes_artifact_report(self):
        result = self.root / "result.json"
        state = self.root / "state.json"
        output = self.root / "acceptance.json"
        result.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        state.write_text(json.dumps({"status": "completed", "tasks": []}), encoding="utf-8")

        code, report = self.call(
            "overnight-acceptance",
            "--result", str(result),
            "--state", str(state),
            "--output", str(output),
        )

        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.assertTrue(output.is_file())

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

    def test_auto_command_blocks_platform_without_growth_strategy_snapshot(self):
        report = {
            "items": [{"title": "AI workflow", "source": "github", "points": 10, "url": "https://example.test"}],
            "sources": [{"source": "github", "status": "ok", "count": 1}],
            "summary": {"items": 1},
        }
        with patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
            code, result = self.call("auto", "--platform", "zhihu", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(result[0]["state"], "blocked")
        self.assertEqual(result[0]["last_error"], "growth strategy snapshot missing")

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
        self.call(
            "record-performance",
            created["id"],
            "--platform",
            "wechat",
            "--views",
            "100",
            "--likes",
            "12",
            "--comments",
            "3",
            "--shares",
            "2",
            "--saves",
            "7",
            "--follows",
            "4",
            "--completion-rate",
            "0.58",
            "--three-second-view-rate",
            "0.73",
            "--avg-watch-seconds",
            "36.5",
            "--metric",
            "coin_rate=0.08",
            "--metric",
            "note=manual",
        )
        code, result = self.call("feedback-summary")
        self.assertEqual(code, 0)
        self.assertEqual(result["platforms"]["wechat"]["views"], 100)
        self.assertEqual(result["platforms"]["wechat"]["saves"], 7)
        self.assertEqual(result["platforms"]["wechat"]["follows"], 4)
        self.assertEqual(result["platforms"]["wechat"]["completion_rate"], 0.58)
        self.assertEqual(result["platforms"]["wechat"]["extra_metrics"]["coin_rate"], 0.08)

    def test_project_audit_command_reports_clean_repo(self):
        with chdir(self.root):
            code, result = self.call("project-audit")
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIn("scanned_files", result)

    def test_task_market_auto_without_key_returns_clean_skip_result(self):
        # Do not let a server-side AiToEarn credential turn this no-key unit
        # test into a real client path.
        with patch.dict("os.environ", {}, clear=True):
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
