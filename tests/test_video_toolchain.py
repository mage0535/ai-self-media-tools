import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.generator import DraftGenerator
from content_platform.strategy_router import choose_content_strategy
from content_platform.video_recipe import build_visual_recipe
from content_platform.video_toolchain import build_video_toolchain_plan


class VideoToolchainTests(unittest.TestCase):
    def test_embedded_licensed_bgm_is_the_only_route_loading_generic_bgm_resolver(self):
        embedded = build_video_toolchain_plan(
            {
                "primary_platforms": ["tiktok"],
                "content_form": "short_video",
                "audio_plan": {
                    "route": "embedded_licensed_bgm",
                    "route_reason": "licensed bed supports narration",
                    "source_audio_action": "replace",
                    "fallback_route": "sfx_only",
                    "license": "Pixabay Content License",
                    "source_url": "https://pixabay.com/music/bed",
                    "fingerprint": "sha256:bed",
                    "rights_scope": "worldwide_social_video",
                },
            },
            {"topic": "AI workflow"},
        )
        native = build_video_toolchain_plan(
            {
                "primary_platforms": ["tiktok"],
                "content_form": "short_video",
                "audio_plan": {
                    "route": "platform_native_track",
                    "route_reason": "native trend evidence",
                    "source_audio_action": "replace_at_publish",
                    "fallback_route": None,
                    "platform": "tiktok",
                    "track_id": "track-123",
                    "track_url": "https://www.tiktok.com/music/track-123",
                    "trend_evidence": {"rank": 4},
                    "rights_scope": "tiktok_native_use",
                    "apply_stage": "platform_publish",
                },
            },
            {"topic": "AI workflow"},
        )

        self.assertIn("online_real_instrument_bgm_resolver", embedded["required_tools"])
        self.assertNotIn("online_real_instrument_bgm_resolver", native["required_tools"])
        self.assertIn("platform_native_track_applicator", native["required_tools"])
        self.assertNotIn("download_bgm", native["renderer_steps"])
        self.assertNotIn("licensed_bgm_mix", native["effect_stack"])
        self.assertEqual(native["audio_plan"]["route"], "platform_native_track")

    def test_original_video_without_audio_plan_records_resolution_required(self):
        plan = build_video_toolchain_plan(
            {"primary_platforms": ["tiktok"], "content_form": "short_video"},
            {"topic": "AI workflow"},
        )

        self.assertEqual(plan["audio_plan"]["route"], "resolution_required")
        self.assertEqual(plan["audio_plan"]["status"], "resolution_required")
        self.assertIn("audio_plan_resolver", plan["required_tools"])
        self.assertIn("resolve_audio_plan", plan["renderer_steps"])

    def test_empty_bound_audio_plan_records_resolution_required(self):
        plan = build_video_toolchain_plan(
            {"primary_platforms": ["douyin_pet"], "content_form": "short_video", "audio_plan": {}},
            {"topic": "cat nap", "audio_plan": {}},
        )

        self.assertEqual(plan["audio_plan"]["route"], "resolution_required")

    def test_pet_plan_carries_the_account_lane_for_the_render_gate(self):
        from content_platform.account_lane_gate import validate_account_lane

        plan = build_video_toolchain_plan(
            {"primary_platforms": ["douyin_pet"], "content_form": "short_video"},
            {"topic": "cat nap", "lane": "pet_healing", "account_key": "douyin_pet", "content_line": "healing_moments"},
        )

        self.assertTrue(validate_account_lane(plan)["passed"])

    def test_original_ai_workflow_rejects_even_approved_sfx_only(self):
        with self.assertRaisesRegex(ValueError, "sfx_only_conflicts_with_bgm_requirement"):
            build_video_toolchain_plan(
                {
                    "primary_platforms": ["tiktok"],
                    "content_form": "short_video",
                    "audio_plan": {
                        "route": "sfx_only",
                        "route_reason": "explicit no-music request",
                        "source_audio_action": "replace_with_voiceover_and_sfx",
                        "fallback_route": None,
                        "no_bgm_approved": True,
                        "approval_source": "explicit_user_request",
                    },
                },
                {"topic": "AI workflow", "content_line": "original AI explainer"},
            )

    def test_approved_sfx_only_repost_does_not_claim_bgm_download_or_mix(self):
        plan = build_video_toolchain_plan(
            {
                "primary_platforms": ["douyin"],
                "content_form": "short_video",
                "asset_plan": ["source_video"],
                "audio_plan": {
                    "route": "sfx_only",
                    "route_reason": "explicit no-music request",
                    "source_audio_action": "replace_with_voiceover_and_sfx",
                    "fallback_route": None,
                    "no_bgm_approved": True,
                    "approval_source": "explicit_user_request",
                },
            },
            {"topic": "cat behavior", "content_line": "localized repost"},
        )

        self.assertNotIn("download_bgm", plan["renderer_steps"])
        self.assertNotIn("mix_audio", plan["renderer_steps"])
        self.assertNotIn("audio_mixer", plan["required_tools"])
        self.assertNotIn("licensed_bgm_mix", plan["effect_stack"])

    def test_platform_alone_does_not_force_original_tiktok_ai_video_into_repost(self):
        plan = build_video_toolchain_plan(
            {
                "primary_platforms": ["tiktok"],
                "content_form": "short_video",
                "asset_plan": ["short_video", "knowledge_cards"],
            },
            {
                "topic": "Power Automate invoice matching",
                "content_line": "real world AI implementation",
            },
        )

        self.assertEqual(plan["selected_pipeline"], "knowledge_card_video")
        self.assertNotIn("source_video_discovery", plan["required_tools"])

    def test_douyin_platform_alone_never_forces_ai_content_into_pet_template(self):
        plan = build_video_toolchain_plan(
            {
                "primary_platforms": ["douyin"],
                "content_form": "short_video",
                "asset_plan": ["short_video", "knowledge_cards"],
                "audio_plan": {
                    "route": "embedded_licensed_bgm",
                    "route_reason": "licensed bed supports narration",
                    "source_audio_action": "replace",
                    "fallback_route": "sfx_only",
                    "license": "Pixabay Content License",
                    "source_url": "https://pixabay.com/music/bed",
                    "fingerprint": "sha256:bed",
                    "rights_scope": "worldwide_social_video",
                },
            },
            {
                "topic": "AI 自动核对重复发票",
                "content_line": "real world AI implementation",
                "primary_track": "finance operations",
                "audience": "invoice reviewers",
            },
        )

        self.assertEqual(plan["template_family"], "knowledge_card_motion_case")

    def test_explicit_source_video_still_routes_douyin_pet_work_to_repost(self):
        plan = build_video_toolchain_plan(
            {
                "primary_platforms": ["douyin"],
                "content_form": "short_video",
                "asset_plan": ["source_video"],
            },
            {"topic": "cat behavior", "content_line": "localized repost"},
        )

        self.assertEqual(plan["selected_pipeline"], "localized_repost_video")
        self.assertIn("source_video_discovery", plan["required_tools"])

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
        self.assertIn("visual_recipe", plan)
        self.assertEqual(plan["visual_recipe"]["template_family"], "pet_repost_real_behavior")
        self.assertGreaterEqual(len(plan["visual_recipe"]["modules"]), 3)
        self.assertTrue(str(plan["visual_recipe"]["fingerprint"]).startswith("sha256:"))
        self.assertIn("scene_to_script_mapping", plan["quality_gates"])
        self.assertIn("visual_recipe_recorded", plan["quality_gates"])
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
        for step in ["cinema_storyboard", "shotcraft_motion_plan", "render_cards", "gen_tts", "resolve_audio_plan", "encode_final", "visual_gate_cinema"]:
            self.assertIn(step, plan["renderer_steps"])
        self.assertIn("cinema_color_css", plan["effect_stack"])
        self.assertIn("shotcraft_motion_css", plan["effect_stack"])
        self.assertIn("tools_capability_analysis", plan)
        self.assertIn("tool_selection_plan", plan)
        self.assertTrue(plan["tools_capability_analysis"]["all_relevant_tool_types_analyzed"])
        self.assertGreaterEqual(len(plan["tool_selection_plan"]["selected_tools"]), 6)

    def test_visual_recipe_splits_core_and_instance_fingerprints(self):
        base = {
            "selected_pipeline": "knowledge_card_video",
            "content_form": "knowledge_card_video",
            "template_family": "knowledge_card_motion_case",
            "platforms": ["kuaishou"],
        }

        first = build_visual_recipe(base, title="First topic")
        second = build_visual_recipe({**base, "platforms": ["douyin"]}, title="Second topic")

        # Content-driven platform adaptation intentionally changes the core visual
        # recipe; cross-platform reuse is prevented by family/platform guards.
        self.assertNotEqual(first["core_fingerprint"], second["core_fingerprint"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertTrue(first["style_variants"]["variant_driven"])
        self.assertTrue(first["auto_generated"])
        self.assertTrue(first["requires_visual_asset_resolution"])

    def test_visual_recipe_core_keeps_explicit_style_differences(self):
        base = {
            "selected_pipeline": "knowledge_card_video",
            "content_form": "knowledge_card_video",
            "template_family": "knowledge_card_motion_case",
            "platforms": ["kuaishou"],
        }

        first = build_visual_recipe({**base, "text_layout": "timeline_cards"}, title="Same topic")
        second = build_visual_recipe({**base, "text_layout": "diagonal_hook_cards"}, title="Same topic")

        self.assertNotEqual(first["core_fingerprint"], second["core_fingerprint"])
        self.assertFalse(first["style_variants"]["variant_driven"])

    def test_strategy_router_does_not_add_video_plan_for_wechat_article(self):
        strategy = choose_content_strategy(
            "AI tool workflow",
            {"platforms": ["wechat"], "audience": "operators"},
            {"total_score": 0.62, "dimensions": {"visual_promise": 0.4, "utility": 0.8}, "trend_stage": "emerging"},
            {"style_signature": {"formats": ["article"]}, "platform_distribution": {"wechat": 3}, "account_count": 2},
        )

        self.assertFalse(strategy["video_toolchain_plan"]["required"])

    def test_strategy_router_treats_douyin_ai_as_a_video_lane_even_with_modest_visual_score(self):
        strategy = choose_content_strategy(
            "AI workflow walkthrough",
            {"platforms": ["douyin_ai"], "audience": "builders"},
            {"total_score": 0.6, "dimensions": {"visual_promise": 0.55, "utility": 0.85}, "trend_stage": "emerging"},
            {"style_signature": {"formats": []}, "platform_distribution": {}, "account_count": 0},
        )

        self.assertEqual(strategy["content_form"], "knowledge_card_video")
        self.assertTrue(strategy["video_toolchain_plan"]["required"])
        self.assertIn("human_voiceover", strategy["asset_plan"])

    def test_video_generation_prompt_uses_short_eight_beat_contract(self):
        requirement, style_limit = DraftGenerator._generation_requirements({
            "strategy": {"content_form": "knowledge_card_video", "primary_platforms": ["douyin_ai"]}
        })

        self.assertIn("exactly eight short paragraphs", requirement)
        self.assertEqual(style_limit, 1800)

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
                "platforms": ["douyin_pet"],
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
                _write_trusted_manifest(video)
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
                "platforms": ["douyin_ai"],
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
                _write_trusted_manifest(video)
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
        "motion_evidence": {
            "passed": True,
            "duration": 45.0,
            "unique_frame_count": 3,
            "frames": [
                {"offset": 0.25, "sha256": "a", "bytes": 100},
                {"offset": 22.5, "sha256": "b", "bytes": 100},
                {"offset": 44.75, "sha256": "c", "bytes": 100},
            ],
        },
        "segment_motion_evidence": {
            "path": str(video.parent / "segment_motion_evidence.json"),
            "segments": [
                {"index": 1, "move_id": "hero-card", "profile": "hero_reveal"},
                {"index": 2, "move_id": "timeline", "profile": "data_pan"},
                {"index": 3, "move_id": "typewriter", "profile": "type_focus"},
            ],
        },
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


def _write_trusted_manifest(video):
    cover = video.parent / "cover.png"
    cover.write_bytes(b"cover")
    gate_to_checker = {
        "DEDUP_GATED": "dedup",
        "MEDIA_GATED": "media",
        "VISUAL_GATED": "visual",
        "AUDIO_GATED": "audio",
        "COVER_GATED": "cover",
        "PACKAGE_GATED": "package",
    }
    checker_hashes = {}
    for gate, checker in gate_to_checker.items():
        payload = {"checker": checker, "status": "ok"}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        (video.parent / f"{checker}_checker_evidence.json").write_text(
            json.dumps({**payload, "evidence_sha256": digest}), encoding="utf-8"
        )
        checker_hashes[gate] = digest
    hashes = {
        "video": hashlib.sha256(video.read_bytes()).hexdigest(),
        "cover": hashlib.sha256(cover.read_bytes()).hexdigest(),
    }
    identity = {
        "run_id": "test-video-toolchain",
        "revision": 1,
        "attempt_id": "attempt-1",
    }
    manifest = {
        **identity,
        "state": "HANDOFF_READY",
        "artifacts": [
            {"name": "video", "path": str(video), "role": "OUTPUT"},
            {"name": "cover", "path": str(cover), "role": "OUTPUT"},
        ],
        "artifact_sha256": hashes,
        "gate_evidence": [
            {
                **identity,
                "gate": gate,
                "artifact_sha256": hashes,
                "evidence_sha256": checker_hashes[gate],
            }
            for gate in (
                "DEDUP_GATED",
                "MEDIA_GATED",
                "VISUAL_GATED",
                "AUDIO_GATED",
                "COVER_GATED",
                "PACKAGE_GATED",
            )
        ],
    }
    (video.parent / "trusted_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_douyin_pet_scene_contract_uses_pet_beats_not_ai_tutorial_layouts():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from visual_contract_gate import validate_scene_contract
    from content_platform.video_toolchain import PET_SCENE_MODES, _build_scene_contract
    scenes = _build_scene_contract("douyin_pet", {"topic": "两只猫"})
    assert [scene["visual_mode"] for scene in scenes] == list(PET_SCENE_MODES)
    assert validate_scene_contract(scenes, strict_runtime=True)["passed"]
    assert not {"prompt_typewriter", "error_fix_compare"} & {scene["visual_mode"] for scene in scenes}


def test_pet_video_narration_is_frozen_to_the_rendered_beats():
    from content_platform.pipeline import Pipeline
    body = "你是不是也以为家里养两只高智商猫是双倍省心？其实这很可能是灾难级的翻车现场。" * 6
    draft = {"body": body, "draft_meta": {"video_toolchain_plan": {"required": True}}}
    Pipeline._freeze_pet_video_beats(draft, {"douyin_pet": {}})
    meta = draft["draft_meta"]
    assert meta["video_script"] == meta["narration_script"] == MediaBridge.compile_video_script(draft)["script"]
    assert len([line for line in meta["video_script"].splitlines() if line.strip()]) == 8
    untouched = {"body": body, "draft_meta": {}}
    Pipeline._freeze_pet_video_beats(untouched, {"xiaohongshu": {}})
    assert "video_script" not in untouched["draft_meta"]
