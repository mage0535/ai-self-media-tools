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

    def test_xiaohongshu_note_keeps_whole_clauses_paragraphs_and_closing(self):
        # 11-03 CST: [:20]/[:950] slicing cut the title to '...低代码+Agen' and the body inside a table.
        table = "| 评估维度 | 传统工单 | Agent工单 |\n| --- | --- | --- |\n| 告警归并 | 人工 | 自动 |"
        body = "\n\n".join(["## 背景"] + ["这是一段关于告警归并的正文内容，" * 12] * 6 + [table, "最后一段：动手拼个验证流试试看。"])
        job = dict(self.job, title="非研发背景做智能告警：用低代码+Agent搭建数字孪生原型踩坑记录", body=body)
        xhs = format_for_platform(job, "xiaohongshu")
        self.assertEqual(xhs["title"], "非研发背景做智能告警")
        self.assertLessEqual(len(xhs["text"]), 950)
        self.assertTrue(xhs["text"].endswith("最后一段：动手拼个验证流试试看。\n\n" + xhs["ai_assisted_disclosure"]))
        self.assertNotIn("| ---", xhs["text"])
        for block in xhs["text"].split("\n\n")[:-2]:
            self.assertIn(block, ["先看结果：", "背景", "这是一段关于告警归并的正文内容，" * 12,
                                  "· 评估维度｜传统工单｜Agent工单\n· 告警归并｜人工｜自动"])

    def test_xiaohongshu_title_without_clause_never_ends_inside_a_word(self):
        job = dict(self.job, title="用低代码和Agent搭建数字孪生原型的完整踩坑记录")
        title = format_for_platform(job, "xiaohongshu")["title"]
        self.assertLessEqual(len(title), 20)
        self.assertFalse(title.endswith(("Agen", "Age", "Ag", "A")))


if __name__ == "__main__":
    unittest.main()
