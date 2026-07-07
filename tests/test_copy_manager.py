"""Tests for Copy Manager module."""
import json
import tempfile
import unittest
from pathlib import Path

from content_platform.copy_manager import CopyMatrix, format_matrix_content


class CopyMatrixTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.copy_dir = self.root / "copy"
        self.copy_dir.mkdir(parents=True)
        self.matrix = CopyMatrix(str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def _write_copy(self, name, content):
        (self.copy_dir / name).write_text(content, encoding="utf-8")

    def test_list_copy_files_empty(self):
        self.assertEqual(self.matrix.list_copy_files(), [])

    def test_list_copy_files_returns_metadata(self):
        self._write_copy("article1.md", "# Title\nContent")
        files = self.matrix.list_copy_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "article1.md")
        self.assertIn("size", files[0])

    def test_load_copy_returns_content(self):
        self._write_copy("test.md", "# Hello\nWorld")
        content = self.matrix.load_copy("test.md")
        self.assertEqual(content, "# Hello\nWorld")

    def test_load_copy_missing_returns_none(self):
        self.assertIsNone(self.matrix.load_copy("nope.md"))

    def test_load_all_copies_returns_dict(self):
        self._write_copy("a.md", "A")
        self._write_copy("b.md", "B")
        all_copies = self.matrix.load_all_copies()
        self.assertEqual(all_copies, {"a.md": "A", "b.md": "B"})

    def test_pick_copy_deterministic_same_seed(self):
        self._write_copy("x.md", "X")
        self._write_copy("y.md", "Y")
        self._write_copy("z.md", "Z")
        name1, content1 = self.matrix.pick_copy(day_seed=42)
        name2, content2 = self.matrix.pick_copy(day_seed=42)
        self.assertEqual(name1, name2)

    def test_pick_copy_empty_returns_none(self):
        name, content = self.matrix.pick_copy()
        self.assertIsNone(name)
        self.assertIsNone(content)

    def test_publish_log_roundtrip(self):
        self.matrix.log_publish("mastodon", True, "https://m.example.com/1")
        entries = self.matrix.last_publish_log(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["platform"], "mastodon")
        self.assertTrue(entries[0]["ok"])

    def test_publish_log_truncates_long_errors(self):
        self.matrix.log_publish("bluesky", False, "", "x" * 500)
        entries = self.matrix.last_publish_log(1)
        self.assertLess(len(entries[0]["error"]), 300)

    def test_recently_published_tracks_platforms(self):
        self.matrix.log_publish("nostr", True, "https://n.example.com")
        recent = self.matrix.recently_published(days=7)
        self.assertIn("nostr", recent)

    def test_load_content_rules_empty_for_missing_file(self):
        rules = self.matrix.load_content_rules()
        self.assertEqual(rules, {})

    def test_load_content_rules_from_file(self):
        rules_path = self.root / "content_rules.json"
        rules_path.write_text(json.dumps({"channel_rules": {"devto": {"enabled": True}}}))
        rules = self.matrix.load_content_rules()
        self.assertEqual(rules["channel_rules"]["devto"]["enabled"], True)

    def test_load_manifest_empty_for_missing(self):
        self.assertEqual(self.matrix.load_manifest(), {})

    def test_load_manifest_roundtrip(self):
        manifest = {"name": "test-matrix", "version": "1.0"}
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        loaded = self.matrix.load_manifest()
        self.assertEqual(loaded["name"], "test-matrix")


class FormatMatrixContentTests(unittest.TestCase):

    def test_microblog_truncates_long_text(self):
        long_text = "word " * 300
        result = format_matrix_content(long_text, "microblog")
        self.assertLessEqual(len(result["text"]), 500)
        self.assertEqual(result["kind"], "microblog")

    def test_auto_long_form_as_blog(self):
        long_text = "article " * 200
        result = format_matrix_content(long_text, "auto")
        self.assertEqual(result["kind"], "blog")

    def test_auto_short_form_as_microblog(self):
        short_text = "quick update: done"
        result = format_matrix_content(short_text, "auto")
        self.assertEqual(result["kind"], "microblog")

    def test_forum_extracts_title_and_teaser(self):
        text = "# Breaking News\n\nThis is the first paragraph with important news.\n\nMore details..."
        result = format_matrix_content(text, "forum")
        self.assertEqual(result["title"], "Breaking News")
        self.assertIn("important news", result["text"])
        self.assertEqual(result["kind"], "forum")

    def test_blog_extracts_title(self):
        text = "# My Blog Post\n\nBody content here."
        result = format_matrix_content(text, "blog")
        self.assertEqual(result["title"], "My Blog Post")
        self.assertEqual(result["kind"], "blog")


if __name__ == "__main__":
    unittest.main()
