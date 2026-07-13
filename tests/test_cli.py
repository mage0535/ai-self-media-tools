import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from content_platform.cli import main


class CliTests(unittest.TestCase):
    def test_demo_outputs_published_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", db, "--config", str(Path(tmp) / "missing.json"), "demo"])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "published")
        self.assertEqual(result["deliveries"][0]["status"], "drafted")

    def test_health_initializes_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--db", db, "--config", "", "health"])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])

    def test_analyze_topic_returns_strategy_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--db",
                        db,
                        "--config",
                        "",
                        "analyze-topic",
                        "--topic",
                        "Automation visuals",
                        "--brief",
                        '{"platforms":["douyin"],"reference_posts":[{"title":"Hook","body":"1. A\\n2. B\\nSave this.","account_handle":"example_creator"}]}',
                    ]
                )
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["strategy"]["content_form"], "short_video")

    def test_account_report_summarizes_reference_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "state.db")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--db",
                        db,
                        "--config",
                        "",
                        "account-report",
                        "--topic",
                        "Automation visuals",
                        "--brief",
                        '{"reference_posts":[{"title":"Hook","body":"1. A 2. B Save this.","account_handle":"example_creator","platform":"xiaohongshu"}]}',
                    ]
                )
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["account_count"], 1)
        self.assertIn("example_creator", result["top_accounts"])


if __name__ == "__main__":
    unittest.main()
