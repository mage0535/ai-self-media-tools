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

            with patch.dict("os.environ", {"CONTENT_PLATFORM_HOME": str(home), "HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                tools = {name: handler for handler, name, _, _ in mcp_server._tools()}
                result = asyncio.run(tools["reddit_channel_status"]())

        self.assertTrue(result["configured"])
        self.assertTrue(result["trend_enabled"])
        self.assertEqual(result["publisher_type"], "reddit-draft")
        self.assertEqual(result["pending_review_count"], 1)
        self.assertEqual(result["pending_reviews"][0]["platforms"], ["reddit"])

    def test_content_recipe_and_validation_tools_are_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            data = home / "data"
            data.mkdir()
            (home / "config.json").write_text(json.dumps({"data_dir": str(data)}), encoding="utf-8")
            Store(data / "state.db").init()

            packet = {
                "platform": "wechat",
                "content_type": "long_article",
                "title": "Operator checklist",
                "body": "practical paragraph " * 120,
                "sections": ["hook", "case", "method", "proof", "checklist"],
                "section_image_map": [
                    {"section": "hook", "image": "01.png", "purpose": "open the issue"},
                    {"section": "case", "image": "02.png", "purpose": "show the case"},
                    {"section": "method", "image": "03.png", "purpose": "show the method"},
                ],
                "embedded_knowledge_cards": [
                    {"section": "hook", "card_type": "warning", "layout": "big_text", "information_value": "states the risk"},
                    {"section": "case", "card_type": "case", "layout": "split", "information_value": "shows the proof"},
                    {"section": "method", "card_type": "steps", "layout": "timeline", "information_value": "keeps the checklist"},
                ],
                "visual_template_selection": {
                    "selected": "casebook",
                    "ranked_scores": [{"template": "casebook", "score": 90}, {"template": "magazine", "score": 75}],
                },
            }

            with patch.dict("os.environ", {"CONTENT_PLATFORM_HOME": str(home), "HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                tools = {name: handler for handler, name, _, _ in mcp_server._tools()}
                recipe = asyncio.run(tools["build_content_recipe"](json.dumps(packet), "wechat"))
                validation = asyncio.run(tools["validate_content_package"](json.dumps(packet), "wechat"))
                capability = asyncio.run(tools["capability_status"]())

        self.assertIn("article_recipe", recipe)
        self.assertIn("knowledge_card_recipe", recipe)
        self.assertIn("preflight_manifest", validation["failed_dimensions"])
        self.assertIn("tools", capability)
        self.assertIn("video_effect_modules", capability)


if __name__ == "__main__":
    unittest.main()
