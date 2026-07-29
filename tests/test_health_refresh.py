import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.health_refresh import classify_platform_health, refresh_delivery_health


class HealthRefreshTests(unittest.TestCase):
    def test_file_domestic_route_stays_unverified(self):
        with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
            entry = classify_platform_health("douyin", {"type": "file"})

        self.assertEqual(entry["state"], "route_unverified")
        self.assertFalse(entry["can_publish_now"])

    def test_domestic_route_requires_cn_proxy_before_probe(self):
        with patch.dict(os.environ, {}, clear=True):
            entry = classify_platform_health(
                "kuaishou",
                {
                    "type": "social-auto-upload",
                    "project_dir": "/missing",
                    "python_bin": "/missing/python",
                    "platform_name": "kuaishou",
                    "account_name": "main",
                },
            )

        self.assertEqual(entry["state"], "proxy_unavailable")

    def test_xiaohongshu_policy_overrides_valid_route(self):
        with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
            entry = classify_platform_health(
                "xiaohongshu",
                {
                    "type": "social-auto-upload",
                    "project_dir": "/would-not-be-used",
                    "python_bin": "/would-not-be-used",
                    "platform_name": "xiaohongshu",
                    "account_name": "main",
                },
            )

        self.assertEqual(entry["state"], "manual_handoff_only")
        self.assertFalse(entry["can_publish_now"])

    def test_manual_handoff_publisher_reports_manual_only_health(self):
        with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
            entry = classify_platform_health("douyin", {"type": "manual-handoff"})

        self.assertEqual(entry["state"], "manual_handoff_only")
        self.assertFalse(entry["can_publish_now"])

    def test_social_auto_upload_valid_marks_postcheck_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_bin = root / "python"
            python_bin.write_text("placeholder", encoding="utf-8")

            def fake_run(*args, **kwargs):
                return type("Result", (), {"returncode": 0, "stdout": "valid", "stderr": ""})()

            with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
                with patch("content_platform.health_refresh.subprocess.run", side_effect=fake_run):
                    entry = classify_platform_health(
                        "kuaishou",
                        {
                            "type": "social-auto-upload",
                            "project_dir": str(root),
                            "python_bin": str(python_bin),
                            "platform_name": "kuaishou",
                            "account_name": "main",
                            "postcheck_command": "postcheck.py",
                        },
                    )

        self.assertEqual(entry["state"], "usable_with_postcheck_required")
        self.assertTrue(entry["can_publish_now"])
        self.assertTrue(entry["require_postcheck"])

    def test_refresh_writes_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "health.json"
            with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
                result = refresh_delivery_health(
                    {"publishers": {"platforms": {"douyin": {"type": "file"}}}},
                    out,
                )

            saved = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(result["platforms"]["douyin"]["state"], "route_unverified")
        self.assertEqual(saved["platforms"]["douyin"]["state"], "route_unverified")

    def test_known_token_publisher_is_usable_when_secret_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "channels.env"
            env_file.write_text("DEVTO_API_KEY=secret-value\n", encoding="utf-8")
            with patch.dict(os.environ, {"US_PROXY": "socks5://127.0.0.1:1091"}, clear=True):
                entry = classify_platform_health(
                    "devto",
                    {"type": "devto-draft", "api_key_env": "DEVTO_API_KEY", "env_file": str(env_file)},
                )

        self.assertEqual(entry["state"], "usable")
        self.assertTrue(entry["can_publish_now"])


if __name__ == "__main__":
    unittest.main()
