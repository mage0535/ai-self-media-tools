import tempfile
import unittest
from pathlib import Path

from content_platform.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.db")
        self.store.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_lifecycle_is_audited(self):
        job = self.store.create_job("A useful topic", ["wechat", "devto"], {"tone": "plain"})
        self.assertEqual(job["state"], "created")

        self.store.save_draft(job["id"], "Title", "Body", "review", {"hits": ["claim"]}, draft_meta={"hook": "Hook", "image_prompt": "Prompt"})
        self.store.transition(job["id"], {"created"}, "review_required", "draft_ready")
        self.store.record_approval(job["id"], "operator", "approved", "checked")
        self.store.transition(job["id"], {"review_required"}, "approved", "human_approved")

        loaded = self.store.get_job(job["id"])
        self.assertEqual(loaded["platforms"], ["wechat", "devto"])
        self.assertEqual(loaded["state"], "approved")
        self.assertEqual(loaded["draft_meta"]["hook"], "Hook")
        self.assertEqual(len(self.store.events(job["id"])), 5)

    def test_artifact_and_delivery_upserts_are_idempotent(self):
        job = self.store.create_job("Topic", ["file"])
        self.store.add_artifact(job["id"], "image", "/tmp/a.png", "abc")
        self.store.add_artifact(job["id"], "image", "/tmp/a.png", "abc")
        self.store.save_delivery(job["id"], "file", "drafted", "draft-1", "")
        self.store.save_delivery(job["id"], "file", "drafted", "draft-1", "")

        self.assertEqual(len(self.store.artifacts(job["id"])), 1)
        self.assertEqual(len(self.store.deliveries(job["id"])), 1)

    def test_invalid_transition_is_rejected(self):
        job = self.store.create_job("Topic", ["file"])
        with self.assertRaises(ValueError):
            self.store.transition(job["id"], {"approved"}, "published", "invalid")


if __name__ == "__main__":
    unittest.main()
