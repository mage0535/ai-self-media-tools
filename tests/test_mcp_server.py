import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform import mcp_server
from content_platform.store import Store


class McpServerTests(unittest.TestCase):
    def test_reddit_channel_status_tool_reports_management_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            data = home / "data"
            data.mkdir()
            (home / "config.json").write_text(
                json.dumps(
                    {
                        "data_dir": str(data),
                        "trends": {"reddit": {"enabled": True, "subreddits": ["SideProject"]}},
                        "publishers": {"platforms": {"reddit": {"type": "reddit-draft"}}},
                    }
                ),
                encoding="utf-8",
            )
            store = Store(data / "state.db")
            store.init()
            job = store.create_job("Reddit topic", ["reddit"], {})
            store.transition(job["id"], {"created"}, "review_required", "draft_ready")
            store.save_delivery(job["id"], "reddit", "review_required", str(data / "outbox" / "reddit" / f"{job['id']}.json"), "")

            with patch.dict("os.environ", {"CONTENT_PLATFORM_HOME": str(home)}, clear=True):
                tools = {name: handler for handler, name, _, _ in mcp_server._tools()}
                result = asyncio.run(tools["reddit_channel_status"]())

        self.assertTrue(result["configured"])
        self.assertTrue(result["trend_enabled"])
        self.assertEqual(result["publisher_type"], "reddit-draft")
        self.assertEqual(result["pending_review_count"], 1)
        self.assertEqual(result["pending_reviews"][0]["platforms"], ["reddit"])


if __name__ == "__main__":
    unittest.main()
