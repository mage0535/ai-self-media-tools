import tempfile
import unittest
import sqlite3
from pathlib import Path

from content_platform.store import Store


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.db")
        self.store.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_one_owner_can_claim_a_job(self):
        job = self.store.create_job("topic", ["wechat"])
        self.assertTrue(self.store.claim(job["id"], {"created"}, "worker-a", 60, "generating"))
        self.assertFalse(self.store.claim(job["id"], {"created", "generating"}, "worker-b", 60, "generating"))
        self.assertEqual(self.store.get_job(job["id"])["lease_owner"], "worker-a")

    def test_stale_claim_is_recovered(self):
        job = self.store.create_job("topic", ["wechat"])
        self.store.claim(job["id"], {"created"}, "dead-worker", -1, "generating")
        recovered = self.store.recover_stale()
        self.assertEqual(recovered, 1)
        self.assertEqual(self.store.get_job(job["id"])["state"], "failed")

    def test_successful_delivery_cannot_be_downgraded(self):
        job = self.store.create_job("topic", ["wechat"])
        self.store.save_delivery(job["id"], "wechat", "drafted", "media-1", "", "stable-key")
        self.store.save_delivery(job["id"], "wechat", "failed", "", "timeout", "stable-key")
        delivery = self.store.deliveries(job["id"])[0]
        self.assertEqual(delivery["status"], "drafted")
        self.assertEqual(delivery["external_id"], "media-1")

    def test_v1_database_is_migrated_without_losing_jobs(self):
        legacy = Path(self.tmp.name) / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript(
            """
            CREATE TABLE jobs(id TEXT PRIMARY KEY,topic TEXT,brief_json TEXT,platforms_json TEXT,title TEXT DEFAULT '',body TEXT DEFAULT '',state TEXT,risk_level TEXT DEFAULT '',risk_json TEXT DEFAULT '{}',created_at TEXT,updated_at TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY,job_id TEXT,event TEXT,detail_json TEXT,created_at TEXT);
            CREATE TABLE artifacts(id INTEGER PRIMARY KEY,job_id TEXT,kind TEXT,path TEXT,checksum TEXT,created_at TEXT,UNIQUE(job_id,kind,path));
            CREATE TABLE approvals(id INTEGER PRIMARY KEY,job_id TEXT,actor TEXT,decision TEXT,note TEXT,created_at TEXT);
            CREATE TABLE deliveries(id INTEGER PRIMARY KEY,job_id TEXT,platform TEXT,status TEXT,external_id TEXT,error TEXT,updated_at TEXT,UNIQUE(job_id,platform));
            INSERT INTO jobs VALUES('old-job','topic','{}','["wechat"]','','','created','','{}','2026-01-01','2026-01-01');
            """
        )
        conn.commit()
        conn.close()
        store = Store(legacy)
        store.init()
        migrated = store.get_job("old-job")
        self.assertEqual(migrated["profile"], "default")
        self.assertEqual(migrated["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
