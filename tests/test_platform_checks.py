import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from content_platform.platform_checks import evaluate_platform_binding


class PlatformChecksTests(unittest.TestCase):
    def test_missing_requirements_results_in_pending(self):
        result = evaluate_platform_binding("wechat", {"credentials_ref": ""}, {"tools": {"content_tools": {"image_script": {"available": False}}}})
        self.assertEqual(result["status"], "pending")
        self.assertIn("missing", result["error"])

    def test_social_auto_upload_checks_respect_binding_project_dir(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookies = root / "cookies"
            cookies.mkdir()
            (cookies / "bilibili_example.json").write_text("{}", encoding="utf-8")
            result = evaluate_platform_binding(
                "bilibili",
                {"config": {"account_name": "example", "project_dir": str(root)}},
                {
                    "publishers": {
                        "bilibili": {
                            "type": "social-auto-upload",
                            "project_dir_exists": True,
                            "python_bin_exists": True,
                            "cli_probe": {"available": True, "error": ""},
                        }
                    },
                    "tools": {"content_tools": {"video_script": {"available": True}}},
                },
            )
        self.assertEqual(result["status"], "connected")


if __name__ == "__main__":
    unittest.main()
