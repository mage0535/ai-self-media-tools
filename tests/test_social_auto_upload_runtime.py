import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.platform_checks import evaluate_platform_binding
from content_platform.publishers import SocialAutoUploadPublisher, build_publisher
from content_platform.readiness import inspect_delivery_readiness


class SocialAutoUploadRuntimeTests(unittest.TestCase):
    def test_readiness_uses_configured_social_auto_upload_home_and_counts_bilibili(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_bin = root / "venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            (root / "cookies").mkdir()
            (root / "cookies" / "bilibili_<account>.json").write_text("{}", encoding="utf-8")
            (root / "cookies" / "douyin_<account>.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"SOCIAL_AUTO_UPLOAD_HOME": str(root)}):
                with patch("content_platform.readiness.subprocess.run") as run:
                    run.return_value = type("Result", (), {"returncode": 0, "stdout": "usage", "stderr": ""})()
                    result = inspect_delivery_readiness({"publishers": {"platforms": {}}})

            social = result["tools"]["social_auto_upload"]
            self.assertEqual(social["resolved_home"], str(root))
            self.assertTrue(social["cli_probe"]["available"])
            self.assertEqual(social["cookie_counts"]["bilibili"], 1)
            self.assertEqual(social["cookie_counts"]["douyin"], 1)

    def test_platform_binding_accepts_social_auto_upload_bilibili_account_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cookies").mkdir()
            (root / "cookies" / "bilibili_<account>.json").write_text("{}", encoding="utf-8")
            readiness = {
                "tools": {
                    "social_auto_upload": {
                        "project_dir_exists": True,
                        "python_bin_exists": True,
                        "cli_probe": {"available": True, "error": ""},
                    },
                    "content_tools": {"video_script": {"available": True}},
                }
            }
            with patch.dict(os.environ, {"SOCIAL_AUTO_UPLOAD_HOME": str(root)}, clear=True):
                result = evaluate_platform_binding("bilibili", {"account_key": "main"}, readiness)
            self.assertEqual(result["status"], "connected")

    def test_social_auto_upload_bilibili_video_extra_args_are_config_driven(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "demo.mp4"
            video.write_bytes(b"video")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            publisher = build_publisher(
                "bilibili",
                {
                    "publishers": {
                        "platforms": {
                            "bilibili": {
                                "type": "social-auto-upload",
                                "account_name": "<account-alias>",
                                "project_dir": tmp,
                                "python_bin": "python",
                                "video_extra_args": ["--tid", "171"],
                            }
                        }
                    }
                },
                tmp,
            )

            with patch("content_platform.publishers.subprocess.run", side_effect=fake_run):
                result = publisher.deliver(
                    {
                        "id": "job-bili",
                        "title": "Title",
                        "body": "Body",
                        "platform_payload": {"kind": "video", "title": "Title", "caption": "Desc", "hashtags": ["#AI"]},
                        "artifacts": [{"kind": "video", "path": str(video)}],
                    },
                    "bilibili",
                )

            self.assertIsInstance(publisher, SocialAutoUploadPublisher)
            self.assertTrue(result.ok)
            self.assertIn("--tid", calls[1])
            self.assertIn("171", calls[1])

    def test_fallback_publisher_uses_next_backend_when_primary_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "publishers": {
                    "platforms": {
                        "bilibili": {
                            "type": "fallback",
                            "publishers": [
                                {
                                    "type": "social-auto-upload",
                                    "account_name": "<account-alias>",
                                    "project_dir": tmp,
                                    "python_bin": "python",
                                },
                                {
                                    "type": "file",
                                    "outbox": str(Path(tmp) / "outbox"),
                                },
                            ],
                        }
                    }
                }
            }

            def fake_run(command, **kwargs):
                return type("Result", (), {"returncode": 1, "stdout": "invalid", "stderr": ""})()

            with patch("content_platform.publishers.subprocess.run", side_effect=fake_run):
                result = build_publisher("bilibili", config, tmp).deliver(
                    {"id": "job-fallback", "title": "Title", "body": "Body"},
                    "bilibili",
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "drafted")
            self.assertTrue(Path(result.external_id).is_file())


if __name__ == "__main__":
    unittest.main()
