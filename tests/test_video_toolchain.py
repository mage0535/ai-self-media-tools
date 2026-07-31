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
            "shotcraft_motion_designer",
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
            "shotcraft_motion_plan_recorded",
            "tool_invocation_manifest_recorded",
            "post_render_cinema_visual_gate",
            "audio_mix_probe_recorded",
            "renderer_steps_recorded",
        ]:
            self.assertIn(gate, plan["quality_gates"])
        for ref in [
            "cinema_composition_designer",
            "shotcraft_motion_designer",
            "video_toolchain_runner",
            "kuaishou_render",
            "visual_gate",
            "audio_mixer",
        ]:
            self.assertIn(ref, plan["tool_refs"])
        for step in ["cinema_storyboard", "shotcraft_motion_plan", "render_cards", "gen_tts", "mix_audio", "encode_final", "visual_gate_cinema"]:
            self.assertIn(step, plan["renderer_steps"])
        self.assertIn("cinema_color_css", plan["effect_stack"])
        self.assertIn("shotcraft_motion_css", plan["effect_stack"])

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

    def test_media_bridge_prepares_image_assets_for_required_original_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_script = root / "image.py"
            video_script = root / "video.py"
            image_script.write_text("# fixture", encoding="utf-8")
            video_script.write_text("# fixture", encoding="utf-8")
            bridge = MediaBridge(
                {
                    "image": {"enabled": True, "script": str(image_script), "provider": "stock"},
                    "video": {"enabled": True, "script": str(video_script), "visual_image_count": 4},
                    "video_toolchain": {"scripts": {"knowledge_card_video": str(video_script)}},
                },
                root,
            )
            job = {
                "id": "j-video",
                "topic": "AI workflow",
                "title": "AI workflow video",
                "body": "Scene one explains the problem.\n\nScene two explains the method.\n\nScene three gives the checklist.",
                "draft_meta": {
                    "video_toolchain_plan": {
                        "required": True,
                        "selected_pipeline": "knowledge_card_video",
                        "template_family": "knowledge_card_motion_case",
                    }
                },
            }

            def fake_run(command, **kwargs):
                if command[1] == str(image_script):
                    output = Path(command[command.index("--output") + 1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(f"image:{output.name}".encode())
                    return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()
                output_dir = Path(kwargs["env"]["VIDEO_OUTPUT_DIR"])
                assets_path = Path(kwargs["env"]["VIDEO_VISUAL_ASSETS_PATH"])
                assets = json.loads(assets_path.read_text(encoding="utf-8"))
                self.assertEqual(len(assets["assignments"]), 4)
                video = output_dir / "generated.mp4"
                video.write_bytes(b"video")
                manifest = _valid_video_manifest(video)
                manifest["visual_assets"] = assets
                (output_dir / "video_toolchain_runner_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("content_platform.tool_adapters.subprocess.run", side_effect=fake_run):
                artifact = bridge.generate("video", job)

            self.assertTrue(artifact["path"].endswith("generated.mp4"))
            self.assertTrue(Path(artifact["visual_assets"]).is_file())

    def test_video_toolchain_runner_binds_visual_assets_to_cards(self):
        from scripts.video_toolchain_runner import build_cards

        assets = {
            "assignments": [
                {"scene": 1, "background_image": "/tmp/bg_01.jpg"},
                {"scene": 2, "background_image": "/tmp/bg_02.jpg"},
            ]
        }

        cards = build_cards(
            "Problem scene.\n\nMethod scene.\n\nResult scene.",
            "Video title",
            {"selected_pipeline": "knowledge_card_video", "template_family": "knowledge_card_motion_case"},
            cinema_scenes=[{} for _ in range(8)],
            shotcraft_plan={"timeline": [{"name": "hero-card"}]},
            visual_assets=assets,
        )

        self.assertEqual(cards[0]["visual_asset"]["background_image"], "/tmp/bg_01.jpg")
        self.assertEqual(cards[1]["visual_asset"]["background_image"], "/tmp/bg_02.jpg")
        self.assertEqual(cards[2]["visual_asset"]["background_image"], "/tmp/bg_01.jpg")

    def test_video_toolchain_runner_materializes_visual_backgrounds_for_renderer(self):
        from scripts.video_toolchain_runner import _materialize_visual_backgrounds

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            source.write_bytes(b"\xff\xd8" + b"x" * 3000)
            assets = {"assignments": [{"scene": 1, "background_image": str(source), "rights_cleared": True, "real_scene": True}]}

            copied = _materialize_visual_backgrounds(root / "out", assets)

            self.assertEqual(len(copied), 1)
            self.assertTrue((root / "out" / "backgrounds" / "bg_01.jpg").is_file())
            self.assertEqual(assets["assignments"][0]["background_image"], str(root / "out" / "backgrounds" / "bg_01.jpg"))

    def test_kuaishou_packet_requires_bgm_subtitles_and_backgrounds(self):
        from scripts.kuaishou_render import generate_packet

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "final.mp4").write_bytes(b"video")
            args = type("Args", (), {"title": "T", "desc": "", "tags": [], "gh_repo": ""})()

            with self.assertRaisesRegex(AssertionError, "bgm_source"):
                generate_packet(str(root), [{"layout": "cover", "t": "T", "f": "F"}], args)

            (root / "bgm_source.json").write_text(
                json.dumps(
                    {
                        "source": "pixabay_music",
                        "source_url": "https://pixabay.com/music/acoustic-guitar",
                        "license": "Pixabay Content License",
                        "fit_reason": "online acoustic guitar instrumental matched to content",
                        "manifest": {
                            "asset_id": "px1",
                            "license": "Pixabay Content License",
                            "fingerprint": "abc",
                            "source_url": "https://pixabay.com/music/acoustic-guitar",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "subtitles.ass").write_text("x" * 120, encoding="utf-8")
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"\xff\xd8" + b"x" * 3000)

            with patch("scripts.kuaishou_render.subprocess.run", return_value=type("Result", (), {"stdout": "45.0\n"})()):
                packet_path = generate_packet(str(root), [{"layout": "cover", "t": "T", "f": "F"}], args)

            packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
            self.assertEqual(packet["burned_captions"]["position"], "lower_third")
            self.assertEqual(packet["bgm_source"]["source"], "pixabay_music")
            self.assertEqual(packet["bgm"]["source"], "pixabay_music")
            self.assertGreaterEqual(packet["burned_captions"]["margin_v"], 180)
            self.assertEqual(len(packet["background_assets"]), 1)


class CinemaCompositionTests(unittest.TestCase):
    def test_kuaishou_render_detects_image_mime_from_bytes(self):
        from scripts.kuaishou_render import _detect_image_mime

        self.assertEqual(_detect_image_mime(b"\xff\xd8jpeg-bytes", "wrong.png"), "image/jpeg")
        self.assertEqual(_detect_image_mime(b"\x89PNG\r\n\x1a\npng-bytes", "wrong.jpg"), "image/png")
        self.assertEqual(_detect_image_mime(b"RIFFxxxxWEBPwebp-bytes", "wrong.png"), "image/webp")

    def test_kuaishou_render_uses_image_probe_instead_of_png_file_size(self):
        from PIL import Image, ImageDraw
        from scripts.kuaishou_render import _rendered_card_quality

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.png"
            image = Image.new("RGB", (720, 1280), (20, 90, 140))
            draw = ImageDraw.Draw(image)
            for y in range(0, 1280, 80):
                draw.rectangle([0, y, 720, y + 28], fill=(240, 240, 240))
            image.save(path, optimize=True)

            ok, reason = _rendered_card_quality(path)

            self.assertTrue(ok, reason)

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

    def test_visual_gate_cinema_mode_uses_relaxed_size_with_cinema_dna(self):
        from PIL import Image, ImageDraw
        from scripts.visual_gate import check_image
        from scripts import cinema_composition

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "card.png"
            img = Image.new("RGB", (840, 1400), (35, 80, 130))
            draw = ImageDraw.Draw(img)
            for i in range(0, 1400, 90):
                draw.line((0, i, 840, 1400 - i), fill=(230, 230, 230), width=3)
            img.save(img_path, optimize=True)
            self.assertLess(img_path.stat().st_size / 1024, 30)

            with patch.object(cinema_composition, "anti_template_check", return_value={"passed": True, "checks": [], "suggestions": []}):
                ok, reports = check_image(str(img_path), cinema_check=True)

            self.assertTrue(ok, reports)


if __name__ == "__main__":
    unittest.main()


def _valid_video_manifest(video):
    return {
        "ok": True,
        "status": "rendered",
        "output": str(video),
        "cinema_storyboard": [{} for _ in range(8)],
        "shotcraft_motion_plan": {
            "available": True,
            "registry_count": 121,
            "timeline": [{"name": "hero-card"}, {"name": "stagger-fade"}, {"name": "scale-bounce"}],
        },
        "cinema_visual_gate": {"passed": True, "checked_images": [{"image": "card_01.png"}]},
        "toolchain_contract": {
            "planned_tools": [
                "cinema_composition.storyboard",
                "shotcraft_moves.shot_plan_for_text",
                "shotcraft_moves.shot_sequence",
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
