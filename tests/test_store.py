import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_intelligence_tables_exist_after_init(self):
        with self.store.connect() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("source_items", tables)
        self.assertIn("account_snapshots", tables)
        self.assertIn("idea_candidates", tables)
        self.assertIn("tool_inventory", tables)
        self.assertIn("delivery_queue", tables)

    def test_delivery_queue_claim_and_complete_round_trip(self):
        job = self.store.create_job("Topic", ["file"])
        self.store.enqueue_delivery(job["id"], "file", "stage", {"state": "review_required"})
        claimed = self.store.claim_delivery("worker-1", ttl_seconds=60)
        self.assertEqual(claimed["platform"], "file")
        self.assertEqual(claimed["action"], "stage")
        self.store.complete_delivery(claimed["id"], "worker-1", "completed")
        queue = self.store.list_delivery_queue("completed")
        self.assertEqual(len(queue), 1)

    def test_topic_clusters_and_historical_performance_are_queryable(self):
        job = self.store.create_job("Automation visuals", ["wechat"])
        self.store.save_topic_clusters(
            job["id"],
            [{"cluster_key": "automation-visuals", "label": "automation", "score": 0.81, "topic_signals": ["automation", "visuals"]}],
        )
        self.store.record_performance(job["id"], "wechat", views=120, likes=10, comments=3, shares=2)
        clusters = self.store.related_topic_clusters("Automation visuals")
        history = self.store.historical_performance(["wechat"], "Automation visuals")
        self.assertEqual(clusters[0]["cluster_key"], "automation-visuals")
        self.assertIn("wechat", history["platforms"])

    def test_draft_versions_are_recorded(self):
        job = self.store.create_job("Topic", ["wechat"])
        self.store.save_draft(job["id"], "Title A", "Body A", "review", {"hits": []}, draft_meta={"hook": "A"})
        self.store.save_draft(job["id"], "Title B", "Body B", "review", {"hits": []}, draft_meta={"hook": "B"})
        versions = self.store.draft_versions(job["id"])
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["title"], "Title A")

    def test_connect_tolerates_wal_lock_fallback(self):
        real_connect = __import__("sqlite3").connect
        state = {"wal_attempts": 0}

        class WrappedConn:
            def __init__(self, inner):
                self.inner = inner
                self.row_factory = None

            def execute(self, sql, *args):
                if sql == "PRAGMA journal_mode=WAL" and state["wal_attempts"] == 0:
                    state["wal_attempts"] += 1
                    raise __import__("sqlite3").OperationalError("database is locked")
                return self.inner.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.inner, name)

        with patch("content_platform.store.sqlite3.connect", side_effect=lambda *args, **kwargs: WrappedConn(real_connect(*args, **kwargs))):
            with self.store.connect() as conn:
                conn.execute("SELECT 1").fetchone()


if __name__ == "__main__":
    unittest.main()
