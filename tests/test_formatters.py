import unittest

from content_platform.formatters import format_for_platform
from content_platform.profiles import resolve_profile


class FormatterTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "id": "j1",
            "title": "A practical guide to agent workflows",
            "body": "First establish inputs and acceptance criteria. Then generate, review, and publish safely.",
            "topic": "agent workflows",
            "profile": "tech",
            "brief": {"sources": ["https://example.com/source"]},
            "draft_meta": {"hashtags": ["#MCP", "#Agent"], "hook": "先看结果："},
            "artifacts": [],
        }

    def test_profile_resolution_merges_brief_without_losing_policy(self):
        profiles = {"tech": {"niche": "AI engineering", "tone": "precise", "banned_topics": ["get rich quick"]}}
        resolved = resolve_profile(profiles, "tech", {"tone": "direct", "audience": "builders"})
        self.assertEqual(resolved["niche"], "AI engineering")
        self.assertEqual(resolved["tone"], "direct")
        self.assertEqual(resolved["banned_topics"], ["get rich quick"])

    def test_platform_payloads_are_distinct_and_constrained(self):
        xhs = format_for_platform(self.job, "xiaohongshu")
        douyin = format_for_platform(self.job, "douyin")
        short = format_for_platform(self.job, "twitter")
        wechat = format_for_platform(self.job, "wechat")
        self.assertLessEqual(len(xhs["title"]), 20)
        self.assertIn("hashtags", xhs)
        self.assertEqual(xhs["hashtags"][:2], ["#MCP", "#Agent"])
        self.assertIn("script", douyin)
        self.assertLessEqual(len(short["text"]), 280)
        self.assertIn("html", wechat)
        self.assertEqual({xhs["kind"], douyin["kind"], short["kind"], wechat["kind"]}, {"note", "video", "short", "article"})


if __name__ == "__main__":
    unittest.main()
