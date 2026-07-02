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


if __name__ == "__main__":
    unittest.main()
