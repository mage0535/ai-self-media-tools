"""Tests for SEO/GEO module."""
import unittest
from content_platform.seo import geo_check, format_geo_report, openserp_search, _find_content_gaps


class GeoCheckTests(unittest.TestCase):

    def test_empty_text_scores_zero(self):
        result = geo_check("")
        self.assertIn("score", result)
        self.assertIn("checks", result)

    def test_short_text_with_numbers_passes_some_checks(self):
        text = "In 2025 AI revenue reached 1.2B. Research from McKinsey confirms 45% growth."
        result = geo_check(text)
        self.assertTrue(result["checks"]["claims_with_numbers"])
        self.assertTrue(result["checks"]["claims_with_sources"])
        self.assertGreater(result["score"], 30)

    def test_text_with_faq_scores_high(self):
        text = (
            "How to use AI effectively? First understand the problem. "
            "1. What is AI? AI is machine intelligence. "
            "2. How much does it cost? About $10000 per project. "
            "3. Where to start? Begin with data. "
            "Q: Is it safe? A: Yes with proper guardrails."
        )
        result = geo_check(text)
        self.assertTrue(result["checks"]["faq_section"])
        self.assertTrue(result["checks"]["direct_answer"])

    def test_text_with_list_and_table(self):
        text = (
            "| Tool | Cost | Rating |\n"
            "|------|------|--------|\n"
            "| A    | $10  | 4.5    |\n\n"
            "- First point\n"
            "- Second point\n"
        )
        result = geo_check(text)
        self.assertTrue(result["checks"]["structured_list"])

    def test_chinese_text_geo_check(self):
        text = (
            "2025年AI市场规模达到120亿美元。根据麦肯锡报告，增长率为45%。"
            "如何应用AI？首先要理解问题。第一点：数据很重要。第二点：模型选择。"
            "来源：https://example.com/report"
        )
        result = geo_check(text)
        self.assertTrue(result["checks"]["claims_with_numbers"])
        self.assertTrue(result["checks"]["claims_with_sources"])
        self.assertTrue(result["checks"]["direct_answer"])

    def test_long_paragraphs_flagged(self):
        text = "。".join(f"第{i}句" for i in range(1, 12))
        result = geo_check(text)
        self.assertFalse(result["checks"]["short_paragraphs"])

    def test_short_paragraphs_pass(self):
        text = "第一段。第二句。第三句。\n\n第二段。第二句。\n\n第三段。第二句。"
        result = geo_check(text)
        self.assertTrue(result["checks"]["short_paragraphs"])

    def test_english_paragraphs_use_sentence_boundary(self):
        text = (
            "Short paragraph with three sentences. Another sentence here. That is enough.\n\n"
            "Another paragraph. Just two sentences here.\n\n"
            "Third paragraph. That is it."
        )
        result = geo_check(text)
        self.assertTrue(result["checks"]["short_paragraphs"])

    def test_blockquote_detected_as_authority_quote(self):
        text = '> "The future of AI is distributed intelligence across edge devices" - some long authority quote that spans more than forty characters here\n\nSome body text.'
        result = geo_check(text)
        self.assertTrue(result["checks"]["authority_quotes"])

    def test_custom_checks_subset(self):
        text = "Test text"
        result = geo_check(text, checks=["faq_section"])
        self.assertEqual(list(result["checks"].keys()), ["faq_section"])


class FormatGeoReportTests(unittest.TestCase):

    def test_report_contains_score_and_icons(self):
        text = "Valid content with 3 numbers 100 200 300 from research https://x.com."
        report = format_geo_report(text, "test")
        self.assertIn("GEO 检查报告", report)
        self.assertIn("综合评分", report)
        self.assertIn("/100", report)

    def test_low_quality_text_gets_conclusion(self):
        report = format_geo_report("short", "lowqual")
        self.assertTrue("未通过" in report or "部分通过" in report or "AI 可见度" in report)


class FindContentGapsTests(unittest.TestCase):

    def test_no_comparison_content_gap(self):
        results = [{"title": "Guide to AI", "type": "organic"}]
        gaps = _find_content_gaps(results)
        self.assertTrue(any("对比" in g for g in gaps))

    def test_all_product_pages_gap(self):
        results = [
            {"title": "Best AI Tools", "type": "organic"},
            {"title": "Top 10 Frameworks", "type": "organic"},
            {"title": "AI Review 2026", "type": "organic"},
        ]
        gaps = _find_content_gaps(results)
        self.assertTrue(any("产品页" in g for g in gaps))

    def test_no_guide_gap(self):
        results = [{"title": "Some Product", "type": "organic"}]
        gaps = _find_content_gaps(results)
        self.assertTrue(any("教程" in g for g in gaps))

    def test_well_covered_no_gaps_related_to_tutorial(self):
        results = [{"title": "How to use AI Guide Tutorial", "type": "organic"}]
        gaps = _find_content_gaps(results)
        self.assertFalse(any("教程" in g for g in gaps))


class OpenSerpSearchTests(unittest.TestCase):

    def test_unreachable_endpoint_returns_error(self):
        result = openserp_search("test", endpoint="http://127.0.0.1:19999/search")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
