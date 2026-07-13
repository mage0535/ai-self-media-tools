import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from content_platform.metrics import render_metrics
from content_platform.metrics_server import make_server
from content_platform.publishers import AyrshareQuotaStore
from content_platform.store import Store


class MetricsTests(unittest.TestCase):
    def test_metrics_and_performance_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            job = store.create_job("topic", ["wechat"])
            store.record_performance(job["id"], "wechat", views=100, likes=9, comments=2, shares=1)
            metrics = render_metrics(store)
            performance = store.performance(job["id"])
        self.assertIn('hermes_content_jobs{state="created"} 1', metrics)
        self.assertIn('hermes_content_views_total{platform="wechat"} 100', metrics)
        self.assertIn("hermes_content_artifact_bytes", metrics)
        self.assertIn("hermes_content_oldest_review_age_seconds", metrics)
        self.assertIn("hermes_content_last_event_timestamp_seconds", metrics)
        self.assertEqual(performance[0]["likes"], 9)

    def test_metrics_http_endpoint_is_scrapeable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            store.create_job("topic", ["wechat"])
            server = make_server(store.path, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{server.server_port}/metrics", timeout=2) as response:
                    body = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("hermes_content_jobs", body)
            finally:
                server.shutdown()
                server.server_close()

    def test_metrics_include_ayrshare_quota_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            quota = AyrshareQuotaStore(Path(tmp) / "ayrshare_quota.db")
            self.assertTrue(quota.try_reserve("bluesky-primary", "bluesky", 20))
            metrics = render_metrics(store)
        self.assertIn('hermes_content_ayrshare_quota_used{account="bluesky-primary",platform="bluesky"', metrics)
        self.assertIn('} 1', metrics)
        self.assertIn('hermes_content_ayrshare_quota_remaining{account="bluesky-primary",platform="bluesky"', metrics)
        self.assertIn('} 19', metrics)

    def test_feedback_summary_aggregates_platform_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            job = store.create_job("topic", ["wechat"])
            store.record_performance(job["id"], "wechat", views=100, likes=9, comments=2, shares=1)
            summary = store.feedback_summary()
        self.assertEqual(summary["platforms"]["wechat"]["views"], 100)
        self.assertEqual(summary["platforms"]["wechat"]["engagement"], 12)


if __name__ == "__main__":
    unittest.main()
