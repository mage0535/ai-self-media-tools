import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.trends import TrendCollector


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
            with self.assertRaises(FileNotFoundError) as ctx:
                collector.collect(refresh=True)
        message = str(ctx.exception).replace("\\", "/")
        self.assertIn("/external/scripts/trend_collector.py", message)
        self.assertNotIn("/data/external/scripts/", message)


if __name__ == "__main__":
    unittest.main()
