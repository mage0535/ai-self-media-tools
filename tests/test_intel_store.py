import tempfile
import unittest
from pathlib import Path

from content_platform.store import Store


class IntelStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.db")
        self.store.init()
        self.job = self.store.create_job("Topic", ["file"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_persists_source_items_accounts_and_ideas(self):
        self.store.save_source_items(
            self.job["id"],
            [
                {"source_type": "reference_post", "platform": "xiaohongshu", "account_handle": "ops_lab", "title": "Title", "body": "Body"},
                {"source_type": "reference_post", "platform": "douyin", "account_handle": "video_maker", "title": "Title 2", "body": "Body 2"},
            ],
        )
        self.store.save_account_snapshots(
            self.job["id"],
            [{"account_handle": "ops_lab", "platform": "xiaohongshu", "display_name": "Ops Lab", "sample_count": 4}],
        )
        self.store.save_idea_candidates(
            self.job["id"],
            [{"topic": "Automation visuals", "score": 0.81, "content_form": "short_video"}],
        )
        self.assertEqual(len(self.store.source_items(self.job["id"])), 2)
        self.assertEqual(len(self.store.account_snapshots(self.job["id"])), 1)
        self.assertEqual(self.store.idea_candidates(self.job["id"])[0]["topic"], "Automation visuals")

    def test_store_records_tool_inventory_snapshots(self):
        self.store.save_tool_inventory("content-tools", {"ffmpeg": {"available": True}})
        latest = self.store.latest_tool_inventory("content-tools")
        self.assertTrue(latest["payload"]["ffmpeg"]["available"])


if __name__ == "__main__":
    unittest.main()
