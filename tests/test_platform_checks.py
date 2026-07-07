import unittest

from content_platform.platform_checks import evaluate_platform_binding


class PlatformChecksTests(unittest.TestCase):
    def test_missing_requirements_results_in_pending(self):
        result = evaluate_platform_binding("wechat", {"credentials_ref": ""}, {"tools": {"content_tools": {"image_script": {"available": False}}}})
        self.assertEqual(result["status"], "pending")
        self.assertIn("missing", result["error"])


if __name__ == "__main__":
    unittest.main()
