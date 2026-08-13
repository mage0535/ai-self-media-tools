import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.pipeline import Pipeline
from content_platform.store import Store
from content_platform.strategy_router import choose_content_strategy
from content_platform.workflow_runtime import WorkflowBlocked, WorkflowStepRunner


class PlatformQualityGateRuntimeTests(unittest.TestCase):
    def test_enforced_platform_quality_gate_flags_incomplete_wechat_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            pipeline = Pipeline(store, {"data_dir": tmp, "feature_flags": {"channel_auto_workflow_gate": "enforce"}})
            draft = {
                "title": "Short WeChat draft",
                "body": "too short and no inline images",
                "draft_meta": {
                    "strategy": {"primary_platforms": ["wechat"], "content_form": "long_article"},
                    "content_form": "long_article",
                    "media_plan": ["cover", "article"],
                    "quality_gate": {"passed": True},
                },
            }

            gate = pipeline._quality_gate("job-1", draft, {"level": "pass"}, {"score": 80})

            self.assertFalse(gate["passed"])
            platform_gate = gate["gates"]["G6_platform_quality"]
            self.assertFalse(platform_gate["passed"])
            self.assertIn("wechat", platform_gate["platforms"])
            self.assertIn("base_article_quality", platform_gate["results"]["wechat"]["failed_dimensions"])

    def test_strategy_router_treats_shipinhao_as_short_video_platform(self):
        strategy = choose_content_strategy(
            "Video channel retention checklist",
            {"platforms": ["shipinhao"], "audience": "wechat operators", "keywords": ["visual"]},
            {"total_score": 0.82, "dimensions": {"visual_promise": 0.9, "utility": 0.7}, "trend_stage": "hot"},
            {"style_signature": {"formats": ["short_video"]}, "platform_distribution": {"shipinhao": 4}, "account_count": 2},
        )

        self.assertEqual(strategy["content_form"], "short_video")
        self.assertTrue(strategy["video_toolchain_plan"]["required"])
        self.assertEqual(strategy["video_toolchain_plan"]["template_family"], "wechat_ecosystem_microcase")


    def test_required_video_plan_blocks_when_video_media_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            job = store.create_job("Cat short video", ["douyin"], {"platforms": ["douyin"]})
            store.save_draft(
                job["id"],
                "Cat short video",
                "A complete script body",
                "pass",
                {"level": "pass"},
                "test",
                {
                    "video_toolchain_plan": {
                        "required": True,
                        "selected_pipeline": "localized_repost_video",
                        "template_family": "pet_repost_real_behavior",
                    }
                },
            )
            pipeline = Pipeline(store, {"data_dir": tmp, "media": {"video": {"enabled": False}}})
            runner = WorkflowStepRunner(store, "wf_video_required", job["id"])

            with self.assertRaises(WorkflowBlocked):
                pipeline._generate_optional_media(job["id"], "video", runner, ["validate_image_requirements"])

    def test_generation_gate_defers_render_only_video_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            pipeline = Pipeline(store, {"data_dir": tmp, "feature_flags": {"channel_auto_workflow_gate": "enforce"}})
            draft = {
                "title": "Bilibili AI automation walkthrough",
                "body": "A real walkthrough script with steps and evidence.",
                "draft_meta": {
                    "strategy": {"primary_platforms": ["bilibili"]},
                    "content_form": "short_video",
                    "video_toolchain_plan": {"required": True, "selected_pipeline": "tutorial_video"},
                },
            }

            gate = pipeline._generation_platform_quality_gate("job-1", draft, ["bilibili"])

            self.assertTrue(gate["passed"])
            self.assertTrue(gate["results"]["bilibili"]["deferred"])

    def test_media_bridge_prefers_full_draft_body_over_prompt_stub_for_video_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "render_video.py"
            script.write_text("# fixture", encoding="utf-8")
            bridge = MediaBridge({"video": {"enabled": True, "script": str(script)}}, root)
            job = {
                "id": "j1",
                "topic": "Topic",
                "title": "Title",
                "body": "Beat one.\n\nBeat two.\n\nBeat three.",
                "draft_meta": {"video_prompt": "A one-line prompt is not a render script."},
            }
            captured = {}

            def fake_run(self, script_body, title, *, env=None):
                captured["script_body"] = script_body
                output_dir = Path(env["VIDEO_OUTPUT_DIR"])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "final.mp4").write_bytes(b"video")

            with patch("content_platform.media.ScriptVideoProvider.run", new=fake_run):
                bridge.generate("video", job)

            self.assertEqual(captured["script_body"], job["body"])

    def test_media_bridge_rejects_video_toolchain_dry_run_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "render_video.py"
            script.write_text("# fixture", encoding="utf-8")
            bridge = MediaBridge(
                {
                    "video": {"enabled": True, "script": str(script)},
                    "video_toolchain": {"scripts": {"knowledge_card_video": str(script)}},
                },
                root,
            )
            job = {
                "id": "j1",
                "topic": "Topic",
                "title": "Title",
                "body": "Body",
                "draft_meta": {
                    "video_toolchain_plan": {
                        "required": True,
                        "selected_pipeline": "knowledge_card_video",
                        "template_family": "knowledge_card_motion_case",
                    }
                },
            }

            def fake_run(command, **kwargs):
                output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
                output_dir.mkdir(parents=True, exist_ok=True)
                fake = output_dir / "dry_run.mp4"
                fake.write_bytes(b"video-toolchain-dry-run")
                (output_dir / "video_toolchain_runner_manifest.json").write_text(
                    json.dumps({"ok": True, "dry_run": True, "status": "dry_run", "output": str(fake)}),
                    encoding="utf-8",
                )
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    bridge.generate("video", job)

    def test_media_bridge_rejects_required_video_without_toolchain_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "render_video.py"
            script.write_text("# fixture", encoding="utf-8")
            bridge = MediaBridge(
                {
                    "video": {"enabled": True, "script": str(script)},
                    "video_toolchain": {"scripts": {"knowledge_card_video": str(script)}},
                },
                root,
            )
            job = {
                "id": "j1",
                "topic": "Topic",
                "title": "Title",
                "body": "Body",
                "draft_meta": {
                    "video_toolchain_plan": {
                        "required": True,
                        "selected_pipeline": "knowledge_card_video",
                        "template_family": "knowledge_card_motion_case",
                    }
                },
            }

            def fake_run(command, **kwargs):
                output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
                output_dir.mkdir(parents=True, exist_ok=True)
                video = output_dir / "generated.mp4"
                video.write_bytes(b"video")
                (output_dir / "video_toolchain_runner_manifest.json").write_text(
                    json.dumps({"ok": True, "status": "rendered", "output": str(video)}),
                    encoding="utf-8",
                )
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "toolchain_contract"):
                    bridge.generate("video", job)


if __name__ == "__main__":
    unittest.main()
