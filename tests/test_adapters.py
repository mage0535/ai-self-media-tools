import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.notify import Notifier
from content_platform.publishers import FileDraftPublisher, TelegraphPublisher
from scripts.autoclip_adapter import run_autoclip_pipeline


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
            bridge.generate("podcast", {"id": "j1", "topic": "Topic", "body": "Body"})

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

    def test_autoclip_local_video_processing_is_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "local video processing is disabled"):
                run_autoclip_pipeline("https://example.com/video")

    def test_video_bridge_passes_approved_copy_and_discovers_generated_file(self):
        script = self.root / "video_pipeline.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge({"video": {"enabled": True, "script": str(script)}}, self.root)

        def fake_run(command, **kwargs):
            output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "generated.mp4").write_bytes(b"video")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run) as run:
            artifact = bridge.generate("video", {"id": "j1", "topic": "Topic", "body": "Body"})
        command = run.call_args.args[0]
        self.assertNotIn("--output", command)
        self.assertEqual(command[-2:], ["Body", "Topic"])
        self.assertTrue(artifact["path"].endswith("generated.mp4"))

    def test_image_bridge_passes_provider_options_and_reference_image(self):
        script = self.root / "image_gen.py"
        script.write_text("# fixture", encoding="utf-8")
        ref = self.root / "reference.png"
        ref.write_bytes(b"reference")
        bridge = MediaBridge(
            {
                "image": {
                    "enabled": True,
                    "script": str(script),
                    "provider": "gemini",
                    "model": "gemini-test-image",
                    "size": "1024x1024",
                    "quality": "low",
                }
            },
            self.root,
        )

        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"image")
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run) as run:
            artifact = bridge.generate(
                "image",
                {"id": "j1", "topic": "Topic", "body": "Body", "draft_meta": {"image_reference": str(ref)}},
            )
        command = run.call_args.args[0]
        self.assertIn("--provider", command)
        self.assertIn("gemini", command)
        self.assertIn("--model", command)
        self.assertIn("gemini-test-image", command)
        self.assertIn("--input-image", command)
        self.assertEqual(artifact["kind"], "image")

    def test_image_bridge_enriches_weak_draft_image_prompt(self):
        script = self.root / "image_gen.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge({"image": {"enabled": True, "script": str(script), "provider": "pollinations"}}, self.root)

        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"image")
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run) as run:
            bridge.generate(
                "image",
                {"id": "j1", "topic": "AI workflow visual cover", "body": "Body", "draft_meta": {"image_prompt": "AI workflow visual cover"}},
            )
        prompt = run.call_args.args[0][2]
        self.assertIn("professional editorial illustration style", prompt)
        self.assertIn("soft natural lighting", prompt)
        self.assertIn("balanced composition", prompt)

    def test_image_bridge_generates_cover_and_section_map_when_min_count_requires_more(self):
        script = self.root / "image_gen.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge(
            {"image": {"enabled": True, "script": str(script), "provider": "pollinations", "min_count": 3}},
            self.root,
        )

        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"image:{output.name}".encode())
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
            artifact = bridge.generate(
                "image",
                {
                    "id": "j1",
                    "topic": "AI workflow visual cover",
                    "body": "Problem paragraph with enough detail for a section image.\n\nMethod paragraph with enough detail for another section image.",
                    "draft_meta": {"image_prompt": "AI workflow visual cover"},
                },
            )

        self.assertEqual(len(artifact["images"]), 3)
        self.assertEqual(len(artifact["section_image_map"]), 2)
        self.assertTrue((self.root / "artifacts" / "j1" / "section_image_map.json").is_file())

    def test_image_bridge_defaults_to_article_image_package_for_long_form_platforms(self):
        script = self.root / "image_gen.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge({"image": {"enabled": True, "script": str(script), "provider": "stock"}}, self.root)

        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"image:{output.name}".encode())
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
            artifact = bridge.generate(
                "image",
                {
                    "id": "j-article",
                    "topic": "AI workflow",
                    "body": "Opening paragraph.\n\nMethod paragraph.\n\nExample paragraph.",
                    "platforms": ["wechat"],
                },
            )

        self.assertEqual(len(artifact["images"]), 3)
        self.assertEqual(len(artifact["section_image_map"]), 2)

    def test_image_bridge_defaults_to_carousel_image_package_for_xiaohongshu(self):
        script = self.root / "image_gen.py"
        script.write_text("# fixture", encoding="utf-8")
        bridge = MediaBridge({"image": {"enabled": True, "script": str(script), "provider": "stock"}}, self.root)

        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"image:{output.name}".encode())
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

        with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
            artifact = bridge.generate(
                "image",
                {
                    "id": "j-xhs",
                    "topic": "AI workflow",
                    "body": "Slide one.\n\nSlide two.\n\nSlide three.\n\nSlide four.\n\nSlide five.",
                    "platforms": ["xiaohongshu"],
                },
            )

        self.assertEqual(len(artifact["images"]), 6)
        self.assertEqual(len(artifact["section_image_map"]), 5)

    def test_notifier_always_records_local_notification(self):
        notifier = Notifier({"log_path": str(self.root / "notifications.jsonl")})
        result = notifier.send("review_required", {"id": "j1", "title": "Title"})
        self.assertTrue(result["logged"])
        self.assertEqual(len((self.root / "notifications.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_notifier_records_workflow_step_context(self):
        notifier = Notifier({"log_path": str(self.root / "notifications.jsonl")})
        notifier.send("workflow_step_started", {"id": "j1", "title": "Title", "step_name": "generate_content", "workflow_id": "wf_j1"})
        row = json.loads((self.root / "notifications.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["step_name"], "generate_content")
        self.assertIn("step=generate_content", Notifier._message(row))

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

    def test_notifier_message_includes_reddit_management_context(self):
        message = Notifier._message(
            {
                "event": "review_required",
                "job_id": "j-reddit",
                "title": "Reddit launch checklist",
                "state": "review_required",
                "platforms": ["reddit"],
                "deliveries": [{"platform": "reddit", "status": "review_required", "external_id": "outbox/reddit/j-reddit.json"}],
                "review_actions": {"approve": "approve-token", "reject": "reject-token"},
            }
        )
        self.assertIn("platforms=reddit", message)
        self.assertIn("reddit:review_required", message)
        self.assertIn("outbox/reddit/j-reddit.json", message)
        self.assertIn("content-platform review-action approve-token --action approve", message)


if __name__ == "__main__":
    unittest.main()
