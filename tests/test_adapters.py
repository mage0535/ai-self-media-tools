import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.notify import Notifier
from content_platform.publishers import FileDraftPublisher, TelegraphPublisher


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_publisher_writes_platform_ready_draft(self):
        publisher = FileDraftPublisher(self.root / "outbox")
        result = publisher.deliver({"id": "j1", "title": "Title", "body": "Body"}, "wechat")
        self.assertTrue(result.ok)
        payload = json.loads(Path(result.external_id).read_text(encoding="utf-8"))
        self.assertEqual(payload["platform"], "wechat")
        self.assertEqual(payload["status"], "drafted")

    def test_live_publisher_is_disabled_by_default(self):
        result = TelegraphPublisher(live_enabled=False).deliver(
            {"id": "j1", "title": "Title", "body": "Body"}, "telegraph"
        )
        self.assertFalse(result.ok)
        self.assertIn("disabled", result.error)

    def test_media_bridge_rejects_unknown_kind_without_running_process(self):
        bridge = MediaBridge({}, self.root)
        with self.assertRaises(ValueError):
            bridge.generate("audio", {"id": "j1", "topic": "Topic", "body": "Body"})

    def test_media_bridge_can_run_ocr_transcription_and_analysis_providers(self):
        script = self.root / "tool.py"
        script.write_text("# fixture", encoding="utf-8")
        sample = self.root / "sample.png"
        sample.write_bytes(b"fake")
        bridge = MediaBridge(
            {
                "ocr": {"script": str(script)},
                "transcription": {"script": str(script)},
                "analysis": {"script": str(script)},
            },
            self.root,
        )
        completed = type("Result", (), {"returncode": 0, "stdout": '{"summary":"ok"}', "stderr": ""})()
        with patch("content_platform.tool_adapters.subprocess.run", return_value=completed):
            self.assertEqual(bridge.ocr(str(sample))["summary"], "ok")
            self.assertEqual(bridge.transcribe(str(sample))["summary"], "ok")
            self.assertEqual(bridge.analyze(str(sample))["summary"], "ok")

    def test_video_bridge_passes_approved_copy_and_discovers_generated_file(self):
        script = self.root / "video_pipeline.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge({"video": {"enabled": True, "script": str(script)}}, self.root)

        def fake_run(command, **kwargs):
            output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "generated.mp4").write_bytes(b"video")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("content_platform.media.subprocess.run", side_effect=fake_run) as run:
            artifact = bridge.generate("video", {"id": "j1", "topic": "Topic", "body": "Body"})
        command = run.call_args.args[0]
        self.assertNotIn("--output", command)
        self.assertEqual(command[-2:], ["Body", "Topic"])
        self.assertTrue(artifact["path"].endswith("generated.mp4"))

    def test_notifier_always_records_local_notification(self):
        notifier = Notifier({"log_path": str(self.root / "notifications.jsonl")})
        result = notifier.send("review_required", {"id": "j1", "title": "Title"})
        self.assertTrue(result["logged"])
        self.assertEqual(len((self.root / "notifications.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_notifier_can_reuse_hermes_home_channel(self):
        notifier = Notifier(
            {"log_path": str(self.root / "notifications.jsonl"), "network_enabled": True, "hermes_target": "telegram"}
        )
        completed = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch("content_platform.notify.subprocess.run", return_value=completed) as run:
            result = notifier.send("review_required", {"id": "j1", "title": "Title", "state": "review_required"})
        self.assertTrue(result["hermes"])
        self.assertEqual(run.call_args.args[0][:4], ["hermes", "send", "--to", "telegram"])

    def test_notifier_reads_only_named_telegram_values_from_env_file(self):
        env_file = self.root / "hermes.env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=fake-token\nTELEGRAM_HOME_CHANNEL=12345\nUNRELATED=ignore\n", encoding="utf-8")
        notifier = Notifier(
            {
                "log_path": str(self.root / "notifications.jsonl"),
                "network_enabled": True,
                "telegram_env_file": str(env_file),
                "telegram_chat_env": "TELEGRAM_HOME_CHANNEL",
            }
        )
        response = type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda *args: None})()
        with patch("content_platform.notify.urllib.request.urlopen", return_value=response) as urlopen:
            result = notifier.send("review_required", {"id": "j1", "title": "Title", "state": "review_required"})
        self.assertTrue(result["telegram"])
        self.assertIn("fake-token", urlopen.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
