"""Tests for the SEO module (content_platform/seo.py)."""

import json
import unittest
from unittest.mock import patch, MagicMock

from content_platform.seo import search, geo_checklist


class TestSearch(unittest.TestCase):
    """Test SEO search via OpenSERP."""

    @patch("content_platform.seo._openserp_request")
    def test_search_returns_results(self, mock_request):
        mock_request.return_value = {
            "results": [
                {"rank": 1, "title": "AI Tools 2026", "url": "https://example.com", "snippet": "Best AI tools"},
            ],
            "total_results": 1,
            "people_also_ask": [],
            "related_searches": [],
        }
        result = search("AI tools", engine="duck", limit=5)
        self.assertEqual(result["query"], "AI tools")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["title"], "AI Tools 2026")

    def test_search_invalid_engine(self):
        result = search("test", engine="invalid")
        self.assertIn("error", result)

    @patch("content_platform.seo._openserp_request")
    def test_search_handles_error(self, mock_request):
        mock_request.return_value = {"error": "Connection refused"}
        result = search("test", engine="duck")
        self.assertIn("error", result)


class TestGeoChecklist(unittest.TestCase):
    """Test GEO 7-point checklist scoring."""

    def test_full_score(self):
        draft = {
            "title": "10 大 AI 工具评测 2026",
            "body": (
                "总结：本评测覆盖60+AI工具的实战对比。\n\n"
                "根据 ProductHunt 报告，AI 工具市场年增长 200%。\n\n"
                "Q: 哪个最好用？\n"
                "A: Claude Code 排名第一。\n\n"
                "| 工具 | 评分 |\n"
                "| --- | --- |\n"
                "| Claude | 9.5 |\n\n"
                "- 优势：速度快\n"
                '- 劣势：贵'
            ),
        }
        result = geo_checklist(draft)
        self.assertEqual(result["score"], 100.0)
        self.assertTrue(all(result["checks"].values()))

    def test_empty_body(self):
        draft = {"title": "", "body": ""}
        result = geo_checklist(draft)
        self.assertLess(result["score"], 100.0)


class TestAnalyze(unittest.TestCase):
    """Test pyseoanalyzer wrapper."""

    @patch("content_platform.seo._pyseo_analyze")
    def test_analyze_success(self, mock_pyseo):
        mock_pyseo.return_value = {
            "title": "Test Page",
            "word_count": 500,
            "links": 10,
            "issues": [],
            "keywords": ["test"],
        }
        from content_platform.seo import analyze
        result = analyze("https://example.com")
        self.assertEqual(result["title"], "Test Page")
        self.assertEqual(result["words"], 500)


if __name__ == "__main__":
    unittest.main()
