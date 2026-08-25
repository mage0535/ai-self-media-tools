import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.pipeline import Pipeline
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

    def test_publish_receipt_upsert_is_idempotent(self):
        receipt = {
            "status": "blocked",
            "verification_level": "none",
            "platform_content_id": "",
            "url": "",
            "error": "temporary health gate",
        }

        self.store.save_publish_receipt("pkg-1", "juejin", receipt, job_id="job-1")
        receipt["error"] = "updated health gate"
        self.store.save_publish_receipt("pkg-1", "juejin", receipt, job_id="job-1")

        rows = self.store.publish_receipts(content_package_id="pkg-1", platform="juejin")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload"]["error"], "updated health gate")

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



    def test_pipeline_create_persists_platforms_in_brief(self):
        from content_platform.pipeline import Pipeline
        pipeline = Pipeline(self.store, {"data_dir": self.tmp.name})
        job = pipeline.create("Topic", ["devto"], {"audience": "builders"})
        self.assertEqual(job["brief"]["platforms"], ["devto"])
        self.assertEqual(job["brief"]["platform"], "devto")

    def test_pipeline_create_sets_international_language_by_platform(self):
        pipeline = Pipeline(self.store, {"generator": {"allow_fallback": True}})
        job = pipeline.create("开源项目 推荐", ["devto"], {}, "default")
        stored = self.store.get_job(job["id"])
        self.assertEqual(stored["brief"].get("language"), "en")

    def test_pipeline_create_respects_explicit_language_override(self):
        pipeline = Pipeline(self.store, {"generator": {"allow_fallback": True}})
        job = pipeline.create("开源项目 推荐", ["devto"], {"language": "zh"}, "default")
        stored = self.store.get_job(job["id"])
        self.assertEqual(stored["brief"].get("language"), "zh")


    def test_topic_history_is_platform_scoped(self):
        job_a = self.store.create_job("Topic A", ["wechat"])
        job_b = self.store.create_job("Topic A", ["devto"])
        self.store.mark_topic_used("topic-a", "Topic A", "fallback", job_a["id"], platform="wechat")
        self.store.mark_topic_used("topic-a", "Topic A", "fallback", job_b["id"], platform="devto")

        self.assertEqual(self.store.used_topics("wechat"), {"topic-a"})
        self.assertEqual(self.store.used_topics("devto"), {"topic-a"})
        with self.store.connect() as conn:
            count = conn.execute("SELECT count(*) FROM topic_history WHERE fingerprint='topic-a'").fetchone()[0]
        self.assertEqual(count, 2)

    def test_manual_publication_reserves_its_topic_for_all_platforms(self):
        receipt = self.store.record_manual_publication(
            "kuaishou",
            "AI automation pitfalls",
            topic_fingerprint="ai-automation-pitfalls",
            external_id="123456789",
            account_alias="kuaishou_main",
            url="https://www.kuaishou.com/short-video/123456789",
            published_at="2026-08-25T12:00:00+08:00",
            verification={
                "account_alias": "kuaishou_main",
                "content_id": "123456789",
                "url": "https://www.kuaishou.com/short-video/123456789",
                "published_at": "2026-08-25T12:00:00+08:00",
                "source": "management_page_postcheck",
            },
        )

        self.assertEqual(receipt["status"], "published")
        self.assertIn("ai-automation-pitfalls", self.store.used_topics())

    def test_delivery_queue_claim_and_complete_round_trip(self):
        job = self.store.create_job("Topic", ["file"])
        self.store.enqueue_delivery(job["id"], "file", "stage", {"state": "review_required"})
        claimed = self.store.claim_delivery("worker-1", ttl_seconds=60)
        self.assertEqual(claimed["platform"], "file")
        self.assertEqual(claimed["action"], "stage")
        self.store.complete_delivery(claimed["id"], "worker-1", "completed")
        queue = self.store.list_delivery_queue("completed")
        self.assertEqual(len(queue), 1)

    def test_delivery_queue_requeues_completed_item_when_retry_is_requested(self):
        job = self.store.create_job("Topic", ["file"])
        self.store.enqueue_delivery(job["id"], "file", "stage", {"state": "review_required"})
        claimed = self.store.claim_delivery("worker-1", ttl_seconds=60)
        self.store.complete_delivery(claimed["id"], "worker-1", "completed", "stale health")

        self.store.enqueue_delivery(job["id"], "file", "stage", {"state": "review_required", "retry": True})

        queue = self.store.list_delivery_queue()
        self.assertEqual(queue[0]["state"], "queued")
        self.assertEqual(queue[0]["payload"]["retry"], True)

    def test_workflow_lock_is_persistent_and_exclusive(self):
        self.assertTrue(self.store.acquire_workflow_lock("worker-1", "wf-1", ttl_seconds=60))
        self.assertFalse(self.store.acquire_workflow_lock("worker-2", "wf-2", ttl_seconds=60))
        self.assertTrue(self.store.heartbeat_workflow_lock("worker-1", ttl_seconds=60))
        self.assertEqual(self.store.workflow_lock()["owner"], "worker-1")
        self.assertTrue(self.store.release_workflow_lock("worker-1"))
        self.assertTrue(self.store.acquire_workflow_lock("worker-2", "wf-2", ttl_seconds=60))

    def test_workflow_steps_and_reports_are_persisted(self):
        job = self.store.create_job("Topic", ["file"])
        self.store.save_workflow_step("wf-1", job["id"], "file", "run_quality_gate", "BLOCKED", reason_code="quality_gate_failed")
        steps = self.store.workflow_steps(job["id"], "file")
        self.assertEqual(steps[0]["status"], "BLOCKED")
        self.assertEqual(steps[0]["reason_code"], "quality_gate_failed")
        self.store.save_workflow_report("wf-1", job["id"], "file", "blocked", "/tmp/report.md", {"blocked_count": 1})
        report = self.store.workflow_reports(job["id"], "file")[0]
        self.assertEqual(report["summary"]["blocked_count"], 1)

    def test_topic_clusters_and_historical_performance_are_queryable(self):
        job = self.store.create_job("Automation visuals", ["wechat"])
        self.store.save_topic_clusters(
            job["id"],
            [{"cluster_key": "automation-visuals", "label": "automation", "score": 0.81, "topic_signals": ["automation", "visuals"]}],
        )
        self.store.record_performance(
            job["id"],
            "wechat",
            views=120,
            likes=10,
            comments=3,
            shares=2,
            saves=4,
            follows=1,
            completion_rate=0.63,
            three_second_view_rate=0.78,
            avg_watch_seconds=41.2,
        )
        clusters = self.store.related_topic_clusters("Automation visuals")
        history = self.store.historical_performance(["wechat"], "Automation visuals")
        self.assertEqual(clusters[0]["cluster_key"], "automation-visuals")
        self.assertIn("wechat", history["platforms"])
        self.assertEqual(history["platforms"]["wechat"]["saves"], 4)
        self.assertEqual(history["platforms"]["wechat"]["follows"], 1)
        self.assertEqual(history["platforms"]["wechat"]["completion_rate"], 0.63)

    def test_performance_ignores_corrupt_extra_metrics_json(self):
        job = self.store.create_job("Topic", ["wechat"])
        self.store.record_performance(job["id"], "wechat", views=10)
        with self.store.connect() as conn:
            conn.execute("UPDATE performance SET extra_metrics_json='not-json' WHERE job_id=?", (job["id"],))

        rows = self.store.performance(job["id"])

        self.assertEqual(rows[0]["extra_metrics"], {})

    def test_draft_versions_are_recorded(self):
        job = self.store.create_job("Topic", ["wechat"])
        self.store.save_draft(job["id"], "Title A", "Body A", "review", {"hits": []}, draft_meta={"hook": "A"})
        self.store.save_draft(job["id"], "Title B", "Body B", "review", {"hits": []}, draft_meta={"hook": "B"})
        versions = self.store.draft_versions(job["id"])
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["title"], "Title A")

    def test_content_candidates_can_exclude_current_job(self):
        first = self.store.create_job("Automation visuals", ["wechat"])
        second = self.store.create_job("Automation visuals update", ["wechat"])
        candidates = self.store.content_candidates(exclude_job_id=second["id"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], first["id"])

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


class ContentPackagesMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "legacy.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _create_legacy_table(self, columns):
        """Create content_packages table without topic/title to simulate old schema."""
        import sqlite3
        conn = sqlite3.connect(self.path)
        col_defs = ", ".join(f"{n} {t}" for n, t in columns.items())
        conn.execute(f"CREATE TABLE IF NOT EXISTS content_packages ({col_defs}, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("PRAGMA table_info(content_packages)")
        conn.commit()
        conn.close()

    def test_migration_adds_topic_and_title_to_legacy_table(self):
        """Store.init() should add missing topic/title columns to legacy content_packages table."""
        self._create_legacy_table({
            "content_package_id": "TEXT PRIMARY KEY",
            "job_id": "TEXT NOT NULL DEFAULT ''",
            "platform": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'created'",
            "payload_json": "TEXT NOT NULL DEFAULT '{}'",
        })
        store = Store(self.path)
        store.init()
        with store.connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(content_packages)")}
        self.assertIn("topic", cols, "topic column should be added by migration")
        self.assertIn("title", cols, "title column should be added by migration")

    def test_fresh_table_has_topic_and_title(self):
        """A newly created content_packages table should have topic/title columns."""
        store = Store(self.path)
        store.init()
        with store.connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(content_packages)")}
        self.assertIn("topic", cols)
        self.assertIn("title", cols)

    def test_save_content_package_with_topic_and_title(self):
        """save_content_package should write topic/title to migrated table."""
        store = Store(self.path)
        store.init()
        store.save_content_package({
            "content_package_id": "test-pkg-1",
            "job_id": "job-1",
            "platform": "wechat",
            "status": "created",
            "content_type": "article",
            "topic": "测试话题",
            "title": "测试标题",
        })
        pkg = store.content_packages(content_package_id="test-pkg-1")
        self.assertEqual(len(pkg), 1)
        self.assertEqual(pkg[0]["topic"], "测试话题")
        self.assertEqual(pkg[0]["title"], "测试标题")



if __name__ == "__main__":
    unittest.main()
