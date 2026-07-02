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
