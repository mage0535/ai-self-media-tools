import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.strategy_router import choose_content_strategy


class VideoToolchainTests(unittest.TestCase):
    def test_strategy_router_adds_auto_video_toolchain_plan_for_short_video_platform(self):
        strategy = choose_content_strategy(
            "Cat behavior warning signs",
            {"platforms": ["douyin"], "audience": "cat owners", "keywords": ["visual", "cat"]},
            {"total_score": 0.84, "dimensions": {"visual_promise": 0.9, "utility": 0.7}, "trend_stage": "hot"},
            {"style_signature": {"formats": ["short_video"]}, "platform_distribution": {"douyin": 4}, "account_count": 2},
        )

        plan = strategy["video_toolchain_plan"]

        self.assertTrue(plan["required"])
        self.assertEqual(plan["content_form"], "short_video")
        self.assertEqual(plan["selected_pipeline"], "localized_repost_video")
        self.assertIn("source_video_discovery", plan["required_tools"])
        self.assertIn("voiceover", plan["required_tools"])
        self.assertIn("lower_third_subtitles", plan["required_tools"])
        for tool in [
            "cinema_composition_designer",
            "card_renderer",
            "tts_renderer",
            "segment_renderer",
            "concat_renderer",
            "audio_mixer",
            "subtitle_burner",
            "final_encoder",
            "post_render_visual_gate",
        ]:
            self.assertIn(tool, plan["required_tools"])
        self.assertEqual(plan["template_family"], "pet_repost_real_behavior")
        self.assertIn("scene_to_script_mapping", plan["quality_gates"])
        for gate in [
            "cinema_storyboard_recorded",
            "tool_invocation_manifest_recorded",
            "post_render_cinema_visual_gate",
            "audio_mix_probe_recorded",
            "renderer_steps_recorded",
        ]:
            self.assertIn(gate, plan["quality_gates"])
        for ref in [
            "cinema_composition_designer",
            "video_toolchain_runner",
            "kuaishou_render",
            "visual_gate",
            "audio_mixer",
        ]:
            self.assertIn(ref, plan["tool_refs"])
        for step in ["cinema_storyboard", "render_cards", "gen_tts", "mix_audio", "encode_final", "visual_gate_cinema"]:
            self.assertIn(step, plan["renderer_steps"])
        self.assertIn("cinema_color_css", plan["effect_stack"])

    def test_strategy_router_does_not_add_video_plan_for_wechat_article(self):
        strategy = choose_content_strategy(
            "AI tool workflow",
            {"platforms": ["wechat"], "audience": "operators"},
            {"total_score": 0.62, "dimensions": {"visual_promise": 0.4, "utility": 0.8}, "trend_stage": "emerging"},
            {"style_signature": {"formats": ["article"]}, "platform_distribution": {"wechat": 3}, "account_count": 2},
        )

        self.assertFalse(strategy["video_toolchain_plan"]["required"])

    def test_media_bridge_passes_video_toolchain_plan_to_selected_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "render_video.py"
            script.write_text("# fixture", encoding="utf-8")
            bridge = MediaBridge(
                {
                    "video": {"enabled": True, "script": str(script)},
                    "video_toolchain": {
                        "scripts": {"localized_repost_video": str(script)},
                    },
                },
                root,
            )
            job = {
                "id": "j1",
                "topic": "Cat topic",
                "title": "Cat title",
                "body": "Body",
                "draft_meta": {
                    "video_toolchain_plan": {
                        "required": True,
                        "selected_pipeline": "localized_repost_video",
                        "template_family": "pet_repost_real_behavior",
                        "required_tools": ["source_video_discovery", "voiceover"],
                    }
                },
            }

            def fake_run(command, **kwargs):
                output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
                plan_path = Path(kwargs["env"]["VIDEO_TOOLCHAIN_PLAN_PATH"])
                self.assertEqual(json.loads(plan_path.read_text(encoding="utf-8"))["template_family"], "pet_repost_real_behavior")
                output_dir.mkdir(parents=True, exist_ok=True)
                video = output_dir / "generated.mp4"
                video.write_bytes(b"video")
                (output_dir / "video_toolchain_runner_manifest.json").write_text(
                    json.dumps(_valid_repost_video_manifest(video), ensure_ascii=False),
                    encoding="utf-8",
                )
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run) as run:
                artifact = bridge.generate("video", job)

            self.assertTrue(artifact["path"].endswith("generated.mp4"))
            self.assertEqual(run.call_args.args[0][1], str(script))


class CinemaCompositionTests(unittest.TestCase):
    def test_cinema_color_css_is_valid_rgba(self):
        from scripts.cinema_composition import color_narrative, color_to_css

        css = color_to_css(color_narrative("AI 工具 工作流 自动化"))

        self.assertIn("rgba(", css["card_bg"])
        self.assertIn("rgba(", css["card_border"])
        self.assertNotIn("rgba55", css["card_bg"])

    def test_visual_gate_min_size_argument_is_enforced(self):
        import subprocess
        import sys
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "card.png"
            img = Image.new("RGB", (800, 800), (30, 35, 45))
            draw = ImageDraw.Draw(img)
            for i in range(0, 800, 20):
                draw.line((0, i, 800, 800 - i), fill=(50 + i % 200, 120, 180), width=3)
            img.save(img_path)

            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "visual_gate.py"), "--image", str(img_path), "--min-size", "100"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("小于 100KB", proc.stdout)


if __name__ == "__main__":
    unittest.main()


def _valid_video_manifest(video):
    return {
        "ok": True,
        "status": "rendered",
        "output": str(video),
        "cinema_storyboard": [{} for _ in range(8)],
        "cinema_visual_gate": {"passed": True, "checked_images": [{"image": "card_01.png"}]},
        "toolchain_contract": {
            "planned_tools": [
                "cinema_composition.storyboard",
                "video_toolchain_runner.build_cards",
                "kuaishou_render.render_cards",
                "kuaishou_render.gen_tts",
                "kuaishou_render.render_segments",
                "kuaishou_render.concat_video",
                "kuaishou_render.download_bgm",
                "mix_bgm_with_gate.mix_bgm",
                "kuaishou_render.gen_subtitles",
                "kuaishou_render.encode_final",
                "visual_gate.py --cinema",
            ]
        },
    }


def _valid_repost_video_manifest(video):
    return {
        "ok": True,
        "status": "rendered",
        "output": str(video),
        "selected_pipeline": "localized_repost_video",
        "repost_source": {"source_type": "local_source_video", "path": str(video)},
        "source_asset_match": {"passed": True, "mode": "local_source_video"},
        "toolchain_contract": {
            "planned_tools": [
                "source_video_discovery",
                "source_asset_matcher",
                "autoclip_adapter.run_autoclip_pipeline",
                "source_dedup_db",
                "ffmpeg.clip_segments",
                "ffmpeg.concat",
                "repost_rights_manifest",
            ]
        },
    }
