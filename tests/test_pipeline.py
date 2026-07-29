import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from content_platform.models import DeliveryResult
from content_platform.pipeline import Pipeline
from content_platform.store import Store


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / "state.db")
        self.store.init()
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "risk": {"block_words": ["blocked-word"], "review_words": ["guaranteed"]},
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end_requires_approval_and_is_idempotent(self):
        job = self.pipeline.create("Practical automation", ["wechat", "xiaohongshu"], {"audience": "operators"})
        reviewed = self.pipeline.run(job["id"])
        self.assertEqual(reviewed["state"], "review_required")

        with self.assertRaises(PermissionError):
            self.pipeline.publish(job["id"])

        self.pipeline.approve(job["id"], "operator", "content checked")
        published = self.pipeline.publish(job["id"])
        repeated = self.pipeline.publish(job["id"])
        self.assertEqual(published["state"], "partial")
        self.assertEqual(repeated["state"], "partial")
        self.assertEqual(len(self.store.deliveries(job["id"])), 2)

    def test_blocked_content_cannot_be_approved(self):
        job = self.pipeline.create("blocked-word", ["file"])
        blocked = self.pipeline.run(job["id"])
        self.assertEqual(blocked["state"], "blocked")
        with self.assertRaises(ValueError):
            self.pipeline.approve(job["id"], "operator", "")

    def test_rejection_is_terminal_for_publish(self):
        job = self.pipeline.create("Ordinary topic", ["file"])
        self.pipeline.run(job["id"])
        rejected = self.pipeline.reject(job["id"], "operator", "rewrite")
        self.assertEqual(rejected["state"], "rejected")
        with self.assertRaises(PermissionError):
            self.pipeline.publish(job["id"])

    def test_run_can_auto_stage_review_required_drafts(self):
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "delivery": {"auto_stage_review_required": True},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        reviewed = self.pipeline.run(job["id"])
        self.assertEqual(reviewed["state"], "review_required")
        deliveries = self.store.deliveries(job["id"])
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "drafted")
        queue = self.store.list_delivery_queue("completed")
        self.assertEqual(len(queue), 1)

    def test_run_persists_intelligence_records(self):
        job = self.pipeline.create(
            "Automation visuals",
            ["wechat"],
            {"platforms": ["wechat", "douyin"], "reference_posts": [{"title": "Hook", "body": "1. A\n2. B\nSave this.", "account_handle": "example_creator"}]},
        )
        self.pipeline.run(job["id"])
        self.assertTrue(self.store.source_items(job["id"]))
        self.assertTrue(self.store.account_snapshots(job["id"]))
        self.assertTrue(self.store.idea_candidates(job["id"]))
        self.assertTrue(self.store.topic_clusters(job["id"]))

    def test_publish_uses_delivery_queue(self):
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        published = self.pipeline.publish(job["id"])
        self.assertEqual(published["state"], "partial")
        self.assertTrue(self.store.list_delivery_queue("completed"))
        self.assertTrue(self.store.workflow_reports(job["id"], "wechat"))
        self.assertIn("send_completion_report", [row["step_name"] for row in self.store.workflow_steps(job["id"], "wechat")])

    def test_required_quality_gate_blocks_before_publish(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "wechat_toolchain": {"enabled": False},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        with patch.object(pipeline.generator, "generate", return_value={
            "title": "Title",
            "body": "Body",
            "draft_meta": {"quality_gate": {"passed": False, "failed_dimensions": ["missing_structure"]}},
        }):
            result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        reports = self.store.workflow_reports(job["id"], "")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertTrue(Path(reports[0]["report_path"]).is_file())
        steps = self.store.workflow_steps(job["id"])
        self.assertIn("run_quality_gate", [row["step_name"] for row in steps])
        self.assertEqual([row for row in steps if row["step_name"] == "run_quality_gate"][-1]["status"], "BLOCKED")
        with patch("content_platform.pipeline.build_publisher") as publisher:
            with self.assertRaises(PermissionError):
                self.pipeline.publish(job["id"])
            publisher.assert_not_called()


    def test_enforced_wechat_requires_professional_toolchain_before_quality_gate(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "wechat_toolchain": {"wewrite_bin": str(Path(self.tmp.name) / "missing_wewrite")},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        steps = self.store.workflow_steps(job["id"])
        toolchain = [row for row in steps if row["step_name"] == "prepare_wechat_professional_toolchain"][-1]
        self.assertEqual(toolchain["status"], "BLOCKED")
        self.assertEqual(toolchain["reason_code"], "wechat_toolchain_unavailable")

    def test_required_image_gate_blocks_when_artifact_missing(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "media": {"image": {"enabled": True, "required": True, "min_count": 1}},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        with patch.object(pipeline.media, "generate", return_value=None):
            result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        image_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "generate_or_collect_images"][-1]
        self.assertEqual(image_step["status"], "BLOCKED")

    def test_delivery_worker_processes_one_item_by_default(self):
        job = self.pipeline.create("Practical automation", ["wechat", "devto"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        for platform in job["platforms"]:
            self.store.enqueue_delivery(job["id"], platform, "publish", {"state": "approved"})
        processed = self.pipeline.process_delivery_queue()
        self.assertEqual(processed, 1)
        self.assertEqual(len(self.store.list_delivery_queue("completed")), 1)
        self.assertEqual(len(self.store.list_delivery_queue("queued")), 1)

    def test_failed_publish_attempt_is_not_recorded_as_succeeded_step(self):
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        self.store.enqueue_delivery(job["id"], "wechat", "publish", {"state": "approved"})
        with patch.object(self.pipeline, "_deliver", return_value=DeliveryResult(False, "failed", error="temporary timeout")):
            processed = self.pipeline.process_delivery_queue()
        self.assertEqual(processed, 1)
        step = [row for row in self.store.workflow_steps(job["id"], "wechat") if row["step_name"] == "publish_or_create_draft"][-1]
        self.assertEqual(step["status"], "FAILED_RETRYABLE")
        self.assertEqual(len(self.store.list_delivery_queue("queued")), 1)

    def test_run_skips_local_video_and_audio_generation_by_default_policy(self):
        root = Path(self.tmp.name)
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "media": {
                    "video": {"enabled": True, "script": str(root / "missing-video.py")},
                    "audio": {"enabled": True},
                },
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )
        job = self.pipeline.create("Visual workflow", ["douyin"], {"platforms": ["douyin"], "keywords": ["visual"]})
        reviewed = self.pipeline.run(job["id"])

        self.assertEqual(reviewed["state"], "review_required")
        failed_media = [event for event in self.store.events(job["id"]) if event["event"] == "media_failed"]
        self.assertFalse(any('"video"' in event["detail_json"] or '"audio"' in event["detail_json"] for event in failed_media))

    def test_run_blocks_near_duplicate_topic_before_generation(self):
        original = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        self.pipeline.run(original["id"])

        duplicate = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        blocked = self.pipeline.run(duplicate["id"])

        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["title"], "")
        events = self.store.events(duplicate["id"])
        self.assertTrue(any(event["event"] == "content_hygiene_blocked" for event in events))

    def test_run_marks_overlap_topics_for_review_when_not_blocked(self):
        root = Path(self.tmp.name)
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "content_hygiene": {"block_threshold": 0.95, "review_threshold": 0.2},
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )
        original = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        self.pipeline.run(original["id"])

        derivative = self.pipeline.create("Automation workflow visuals", ["wechat"], {"audience": "operators"})
        reviewed = self.pipeline.run(derivative["id"])

        self.assertEqual(reviewed["state"], "review_required")
        self.assertEqual(reviewed["risk_level"], "review")
        self.assertEqual(reviewed["draft_meta"]["content_hygiene"]["status"], "review")
        self.assertTrue(reviewed["draft_meta"]["cornerstone_mode"])


if __name__ == "__main__":
    unittest.main()
