import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.trends import DirectTrendSource, RedditTrendCollector, TrendCollector


class TrendTests(unittest.TestCase):
    def test_reads_latest_legacy_trends_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trending_2026-06-29.json").write_text(json.dumps({"trends": [{"title": "Old"}]}), encoding="utf-8")
            (root / "trending_2026-06-30.json").write_text(
                json.dumps({"trends": [{"title": "New", "source": "hn"}, {"title": "New", "source": "other"}]}),
                encoding="utf-8",
            )
            trends = TrendCollector({"legacy_data_dir": str(root), "direct_sources": False}).collect(refresh=False)
        self.assertEqual([item["title"] for item in trends], ["New"])

    def test_refresh_default_script_path_uses_project_external_dir(self):
        collector = TrendCollector({"direct_sources": False})
        with patch("content_platform.trends.Path.is_file", return_value=False):
            with patch("content_platform.trends.Path.glob", return_value=[]):
                trends = collector.collect(refresh=True)
        self.assertEqual(trends, [])

    def test_reddit_collector_uses_oauth_and_normalizes_heat_signals(self):
        payload = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Practical AI workflow launch checklist",
                            "permalink": "/r/SideProject/comments/abc/demo/",
                            "score": 120,
                            "num_comments": 45,
                            "upvote_ratio": 0.91,
                            "created_utc": 1783880000,
                            "subreddit": "SideProject",
                        }
                    }
                ]
            }
        }

        class FakeResponse:
            headers = {"X-Ratelimit-Remaining": "99"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(payload).encode()

        config = {
            "enabled": True,
            "access_token": "token",
            "subreddits": ["SideProject"],
            "keywords": ["AI workflow"],
            "limit_per_subreddit": 10,
        }
        with patch("content_platform.trends.urllib.request.urlopen", return_value=FakeResponse()) as call:
            trends = RedditTrendCollector(config).collect()

        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0]["source"], "reddit:SideProject")
        self.assertEqual(trends[0]["url"], "https://www.reddit.com/r/SideProject/comments/abc/demo/")
        self.assertGreater(trends[0]["points"], 120)
        self.assertEqual(trends[0]["keywords"], ["AI workflow"])
        self.assertIn("Bearer token", call.call_args.args[0].headers["Authorization"])

    def test_trend_collector_can_merge_reddit_source(self):
        with patch("content_platform.trends.RedditTrendCollector.collect", return_value=[{"title": "Reddit topic", "source": "reddit:AI", "points": 3}]):
            trends = TrendCollector({"reddit": {"enabled": True}, "direct_sources": False}).collect(refresh=False)
        self.assertEqual(trends, [{"title": "Reddit topic", "source": "reddit:AI", "points": 3}])

    def test_direct_hackernews_source_normalizes_items(self):
        payload = {"hits": [{"title": "AI agents need better workflow gates", "url": "https://example.com/a", "points": 88, "num_comments": 12}]}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(payload).encode()

        with patch("content_platform.trends.urllib.request.urlopen", return_value=FakeResponse()):
            items = DirectTrendSource("hackernews", {"limit": 5}).collect()

        self.assertEqual(items[0]["source"], "hackernews")
        self.assertEqual(items[0]["points"], 88)
        self.assertIn("workflow gates", items[0]["title"])

    def test_collect_with_report_keeps_source_failures_visible(self):
        with patch("content_platform.trends.DirectTrendSource.collect", side_effect=RuntimeError("source unavailable")):
            report = TrendCollector({"direct_sources": {"hackernews": {"enabled": True}}, "fallback_enabled": True}).collect_with_report()

        self.assertEqual(report["summary"]["failed_sources"], 5)
        self.assertTrue(report["summary"]["fallback_used"])
        self.assertGreaterEqual(len(report["items"]), 1)
        self.assertTrue(all(row["status"] == "failed" for row in report["sources"][:5]))

    def test_refresh_legacy_script_timeout_is_reported_not_blocking_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "trend_collector.py"
            script.write_text("print('slow')", encoding="utf-8")
            with patch("content_platform.trends.subprocess.run", side_effect=subprocess.TimeoutExpired(["python3", str(script)], 1)):
                report = TrendCollector({"legacy_script": str(script), "direct_sources": False}).collect_with_report(refresh=True)

        self.assertEqual(report["sources"][0]["source"], "legacy_script")
        self.assertEqual(report["sources"][0]["status"], "failed")
        self.assertIn("timed out", report["sources"][0]["error"])

    def test_bilibili_falls_back_to_web_search_when_api_fails(self):
        with patch.object(DirectTrendSource, "_request_json", side_effect=RuntimeError("blocked")):
            with patch.object(DirectTrendSource, "_duckduckgo_html_search", return_value=[{"title": "B站 AI workflow", "source": "bilibili:web_search", "points": 1}]):
                items = DirectTrendSource("bilibili", {"limit": 5}).collect()

        self.assertEqual(items[0]["source"], "bilibili:web_search")

    def test_zhihu_and_douyin_use_web_search_sources(self):
        with patch.object(DirectTrendSource, "_duckduckgo_html_search", return_value=[{"title": "AI tool topic", "source": "zhihu:web_search", "points": 1}]) as search:
            items = DirectTrendSource("zhihu", {"limit": 5}).collect()

        self.assertEqual(items[0]["title"], "AI tool topic")
        self.assertTrue(search.called)

        with patch.object(DirectTrendSource, "_duckduckgo_html_search", return_value=[{"title": "Douyin AI workflow topic", "source": "douyin:web_search", "points": 1}]) as search:
            items = DirectTrendSource("douyin", {"limit": 5}).collect()

        self.assertEqual(items[0]["source"], "douyin:web_search")
        self.assertTrue(search.called)

    def test_web_search_source_degrades_with_explicit_unavailable_marker(self):
        source = DirectTrendSource("zhihu", {"limit": 5, "source_fallback_enabled": True})
        with patch.object(source, "_searxng_search", return_value=[]), \
            patch.object(source, "_duckduckgo_html_search", return_value=[]), \
            patch.object(source, "_bing_html_search", return_value=[]), \
            patch.object(source, "_baidu_html_search", return_value=[]):
            items = source.collect()

        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(items[0]["source_unavailable"])
        self.assertEqual(items[0]["source"], "zhihu:source_fallback")

    def test_collect_report_marks_source_fallback_as_degraded(self):
        with patch.object(DirectTrendSource, "collect", return_value=[{"title": "Fallback", "source": "zhihu:source_fallback", "source_unavailable": True}]):
            report = TrendCollector({"direct_sources": {"zhihu": {"enabled": True}}}).collect_with_report()

        self.assertEqual(report["sources"][0]["status"], "degraded")
        self.assertEqual(report["summary"]["degraded_sources"], 5)

    def test_wewrite_hotspots_source_normalizes_cli_output(self):
        payload = [{"title": "公众号热点选题", "heat": 42, "url": "https://example.com/w"}]
        completed = type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

        with patch("content_platform.trends.Path.is_file", return_value=True):
            with patch("content_platform.trends.subprocess.run", return_value=completed):
                items = DirectTrendSource("wewrite_hotspots", {"wewrite_bin": "/tmp/wewrite", "limit": 5}).collect()

        self.assertEqual(items[0]["source"], "wewrite_hotspots")
        self.assertEqual(items[0]["points"], 42)
        self.assertEqual(items[0]["title"], "公众号热点选题")


if __name__ == "__main__":
    unittest.main()
