import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(published["state"], "published")
        self.assertEqual(repeated["state"], "published")
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
            {"platforms": ["wechat", "douyin"], "reference_posts": [{"title": "Hook", "body": "1. A\n2. B\nSave this.", "account_handle": "ops_lab"}]},
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
        self.assertEqual(published["state"], "published")
        self.assertTrue(self.store.list_delivery_queue("completed"))


if __name__ == "__main__":
    unittest.main()
