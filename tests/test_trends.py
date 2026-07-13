import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.trends import RedditTrendCollector, TrendCollector


class TrendTests(unittest.TestCase):
    def test_reads_latest_legacy_trends_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trending_2026-06-29.json").write_text(json.dumps({"trends": [{"title": "Old"}]}), encoding="utf-8")
            (root / "trending_2026-06-30.json").write_text(
                json.dumps({"trends": [{"title": "New", "source": "hn"}, {"title": "New", "source": "other"}]}),
                encoding="utf-8",
            )
            trends = TrendCollector({"legacy_data_dir": str(root)}).collect(refresh=False)
        self.assertEqual([item["title"] for item in trends], ["New"])

    def test_refresh_default_script_path_uses_project_external_dir(self):
        collector = TrendCollector({})
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
            trends = TrendCollector({"reddit": {"enabled": True}}).collect(refresh=False)
        self.assertEqual(trends, [{"title": "Reddit topic", "source": "reddit:AI", "points": 3}])


if __name__ == "__main__":
    unittest.main()
