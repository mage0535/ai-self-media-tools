import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch


class VideoToolchainRunnerTests(unittest.TestCase):
    def test_video_cover_uses_shared_platform_director(self):
        from PIL import Image
        from scripts.video_toolchain_runner import _generate_video_cover

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            background = root / "background.jpg"
            Image.new("RGB", (1400, 1800), (20, 30, 50)).save(background)
            result = _generate_video_cover(
                root,
                "别再来回切 AI 工具",
                "一个入口串起文案、图片和语音。",
                {"platforms": ["kuaishou"], "recent_cover_direction_ids": []},
                background,
            )

            self.assertTrue(Path(result["path"]).is_file())
            self.assertEqual(result["evidence"]["platform_profile"], "fast_utility")
            self.assertTrue(result["evidence"]["typography_overlay_verified"])

    def test_renderer_selection_uses_precompiled_video_route_without_late_keyword_override(self):
        from scripts.video_toolchain_runner import _content_driven_renderer

        with tempfile.TemporaryDirectory() as tmp:
            plan = {
                "selected_pipeline": "layered_knowledge_card_video",
                "video_route": {"renderer_id": "layered_card_renderer"},
            }
            renderer, updated = _content_driven_renderer(
                plan,
                "First step. Second step. Compare the result.",
                "A tutorial comparison",
                Path(tmp),
            )

            self.assertEqual(renderer.name, "kuaishou_render.py")
            self.assertEqual(updated["selected_pipeline"], "layered_knowledge_card_video")

    def test_cards_follow_directed_scene_presentations_instead_of_fixed_sequence(self):
        from scripts.video_toolchain_runner import build_cards

        plan = {
            "template_family": "split_comparison",
            "selected_pipeline": "comparison_cinematic_video",
            "video_route": {
                "scene_presentations": [
                    "hero_conflict", "split_screen", "side_a", "side_b",
                    "difference_grid", "evidence_zoom", "winner_reveal", "cta",
                ]
            },
        }
        cards = build_cards("\n\n".join(f"Beat {index}" for index in range(8)), "A vs B", plan)

        assert [card["presentation_mode"] for card in cards] == plan["video_route"]["scene_presentations"]
        assert len({card["layout"] for card in cards}) >= 5
        assert all(card["txt"] != card["tts"] for card in cards)
        assert all(card["tts"] not in " ".join(card.get("items") or []) for card in cards)

    def test_cinema_route_writes_scene_level_visual_treatment_for_renderer(self):
        from PIL import Image
        from scripts.video_toolchain_runner import _write_visual_treatment_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assignments = []
            for index in range(8):
                path = root / f"bg_{index + 1}.jpg"
                Image.new("RGB", (1080, 1920), (index * 20, 30, 50)).save(path)
                assignments.append({"background_image": str(path), "purpose": f"beat {index + 1}"})
            plan = {"video_route": {"presentation_mode": "split_comparison", "scene_presentations": ["split_screen"] * 8}}

            path = _write_visual_treatment_plan(root, plan, assignments)
            payload = json.loads(path.read_text(encoding="utf-8"))

            assert len(payload["scenes"]) == 8
            assert {scene["camera_language"] for scene in payload["scenes"]}
            assert all(scene["real_asset"] for scene in payload["scenes"])

    def test_landscape_renderer_outputs_are_normalized_to_shared_media_contract(self):
        from scripts import video_toolchain_runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render = root / "render"
            (render / "tts").mkdir(parents=True)
            (render / "segments").mkdir()
            (render / "final.mp4").write_bytes(b"video" * 1000)
            (render / "bgm.mp3").write_bytes(b"music" * 1000)
            (render / "bgm_source.json").write_text(json.dumps({"source_url": "https://example.test", "license": "CC BY"}), encoding="utf-8")
            (render / "subtitles.ass").write_text("\n".join(["Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Text"] * 8), encoding="utf-8")
            for index in range(8):
                (render / "tts" / f"tts_{index + 1:02d}.mp3").write_bytes(b"voice" * 1000)
                (render / "segments" / f"seg_{index + 1:02d}.mp4").write_bytes(b"segment" * 1000)
            plan = {"platforms": ["bilibili"], "video_route": {"renderer_id": "landscape_explainer_renderer", "style_id": "style-1", "scene_presentations": ["timeline"] * 8}}
            with patch.object(runner, "_video_duration", return_value=5.0):
                runner._normalize_alternate_renderer_outputs(Path("render_landscape_video.py"), root, plan, "八段真实讲解")

            assert (root / "final.mp4").is_file()
            assert json.loads((root / "tts_fingerprint.json").read_text(encoding="utf-8"))["duration_seconds"] == 40.0
            assert len(json.loads((root / "segment_motion_evidence.json").read_text(encoding="utf-8"))["segments"]) == 8

    def test_scene_execution_evidence_uses_measured_encoded_frames(self):
        from PIL import Image
        from scripts import video_toolchain_runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "final.mp4"
            final.write_bytes(b"video")
            scene_manifest = {"scenes": [{"scene_id": f"s{index + 1:02d}"} for index in range(8)]}
            segment_motion = {"segments": [{"move_id": f"move-{index}", "profile": "cinematic"} for index in range(8)]}
            colors = [(20, 20, 20), (180, 180, 180)] * 8

            with patch.object(runner, "_video_duration", return_value=48.0), patch.object(
                runner, "_sample_video_frame", side_effect=[Image.new("RGB", (64, 64), color) for color in colors]
            ):
                evidence = runner._write_measured_scene_execution(root, final, scene_manifest, segment_motion)

            assert len(evidence["scenes"]) == 8
            assert all(row["frame_difference"] > 0 for row in evidence["scenes"])
            assert all(row["static_ratio"] < 1 for row in evidence["scenes"])

    def test_background_queries_follow_each_script_beat_instead_of_generic_cycle(self):
        from scripts.pexels_auto_bg import _semantic_queries

        script = "\n\n".join([
            "Switching between too many tools wastes attention.",
            "A content creator edits text images and voice.",
            "Open the API dashboard on a developer laptop.",
            "Connect the interface to an automation workflow.",
        ])
        queries = _semantic_queries(script, 4)

        assert len(queries) == 4
        assert len(set(queries)) == 4
        assert any("dashboard" in query or "developer" in query for query in queries)
        assert any("content creator" in query for query in queries)

    def test_short_video_duration_is_normalized_before_artifact_gate(self):
        from scripts import video_toolchain_runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.mp4"
            path.write_bytes(b"original")

            def fake_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b"trimmed")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(runner, "_video_duration", side_effect=[60.8, 59.8]):
                with patch.object(runner.subprocess, "run", side_effect=fake_ffmpeg):
                    result = runner._normalize_short_video_duration(path, "kuaishou")

            self.assertTrue(result["passed"])
            self.assertTrue(result["applied"])
            self.assertEqual(result["duration_seconds"], 59.8)
            self.assertEqual(path.read_bytes(), b"trimmed")

    def test_script_structure_gate_requires_distinct_story_beats(self):
        from scripts.video_toolchain_runner import validate_script_structure

        too_short = validate_script_structure("Only one useful observation.")
        complete = validate_script_structure("\n".join(f"Distinct practical beat {index}." for index in range(1, 9)))

        self.assertFalse(too_short["passed"])
        self.assertIn("story_beats_insufficient", too_short["failures"])
        self.assertTrue(complete["passed"])

    def test_build_cards_does_not_insert_placeholder_copy(self):
        from scripts.video_toolchain_runner import build_cards

        script = "\n".join(f"Specific narrative beat {index}." for index in range(1, 9))
        cards = build_cards(script, "Specific title", {"template_family": "knowledge_card_motion_case"})
        serialized = json.dumps(cards, ensure_ascii=False).casefold()

        self.assertNotIn("keep the visual rhythm", serialized)
        self.assertNotIn("match visual to narration", serialized)
        self.assertNotIn("step 1", serialized)

    def test_build_cards_separates_visual_copy_from_spoken_narration(self):
        from scripts.pre_render_gate import validate_render_inputs
        from scripts.video_toolchain_runner import build_cards

        script = "\n".join([
            "工具越多，创作者每天切换账号和会员的时间越长。",
            "文本、图像、语音和视频能力散落在不同后台。",
            "把这些能力通过 API 接入统一流程，才能减少重复操作。",
            "第一步先确认工具接口和授权范围。",
            "第二步把常用能力接进一个统一入口。",
            "第三步保存每次调用结果和证据。",
            "这样省下来的时间可以回到内容创作。",
            "最后检查输出质量，再决定是否发布。",
        ])
        plan = {"template_family": "knowledge_card_motion_case", "video_route": {"scene_presentations": [
            "hero_conflict", "detail_closeup", "process_flow", "timeline",
            "list_reveal", "evidence_zoom", "payoff_reveal", "cta",
        ]}}

        cards = build_cards(script, "AI 工具越多，效率为什么反而更低？", plan)
        result = validate_render_inputs(Path("."), cards, require_backgrounds=False)

        self.assertTrue(result["passed"], result["failures"])
        self.assertTrue(all(card["txt"] != card["tts"] for card in cards))
        self.assertNotEqual(cards[0]["t"], "AI 工具越多，效率为什么反而更低？")

    def test_cover_background_rejects_foreign_platform_ui_from_ocr(self):
        from scripts.video_toolchain_runner import _select_cover_background

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.jpg"; first.write_bytes(b"one")
            second = Path(tmp) / "second.jpg"; second.write_bytes(b"two")
            outputs = [Mock(stdout="Instagram profile", returncode=0), Mock(stdout="API dashboard", returncode=0)]
            with patch("scripts.video_toolchain_runner.subprocess.run", side_effect=outputs):
                selected, evidence = _select_cover_background([
                    {"background_image": str(first), "purpose": "API workflow", "source_url": "https://pexels.com/photo/interface"},
                    {"background_image": str(second), "purpose": "developer portrait", "source_url": "https://pexels.com/photo/developer"},
                ], "kuaishou")

        self.assertEqual(selected, str(second))
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["ocr_conflicts"], [])

    def test_runner_blocks_non_dry_short_scripts_before_renderer(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps({"platforms": ["kuaishou"]}), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Only one useful observation.", "Useful title"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 5)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "script_structure_failed")

    def test_intl_short_video_pipeline_is_manual_handoff_with_tool_evidence(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "intl_short_video_pipeline.py"
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "CONTENT_PLATFORM_HOME": tmp,
                "PYTHONPATH": str(root),
                "PYTHONIOENCODING": "utf-8",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "--dry-run"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = Path(tmp) / "data" / "intl_video_drafts" / "manifest_"
            manifests = sorted(manifest.parent.glob("manifest_*.json"))
            self.assertTrue(manifests, proc.stdout)
            data = json.loads(manifests[-1].read_text(encoding="utf-8"))
            rows = data["self_gen"] + data["cross_post"]
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(row["status"], "handoff_pending")
                self.assertEqual(row["publish_boundary"], "manual_handoff_only_no_aitoearn")
                self.assertIn("tool_invocation_manifest", row)
                self.assertIn("tools_capability_analysis", row)
                self.assertIn("tool_selection_plan", row)
                self.assertTrue(row["handoff_policy"]["manual_only"])
                self.assertIn("aitoearn_publish", row["handoff_policy"]["forbidden"])

    def test_intl_short_video_pipeline_blocks_aitoearn_for_manual_platforms(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "intl_short_video_pipeline.py"
        spec = importlib.util.spec_from_file_location("intl_short_video_pipeline", script)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with patch.dict(os.environ, {"AITOEARN_INTL_API_KEY": "fake-key"}):
            for platform in ["youtube", "youtube_shorts", "tiktok", "threads"]:
                self.assertFalse(module.publish_video("/tmp/fake.mp4", "title", platform))

    def test_runner_dry_run_materializes_plan_cards_and_output(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Cat workflow"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((out / "dry_run.mp4").is_file())
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cards), 8)
            self.assertEqual(cards[0]["hook"], "Cat workflow")
            self.assertEqual(manifest["template_family"], "pet_repost_real_behavior")
            self.assertTrue((out / "visual_recipe.json").is_file())
            self.assertTrue((out / "pre_render_gate.json").is_file())
            self.assertTrue(manifest["visual_recipe_gate"]["passed"])
            self.assertTrue(manifest["pre_render_gate"]["passed"])
            self.assertTrue(str(manifest["recipe_fingerprint"]).startswith("sha256:"))
            self.assertGreaterEqual(manifest["toolchain_contract"]["visual_recipe"]["module_count"], 3)
            self.assertIn("tools_capability_analysis", manifest)
            self.assertIn("tool_selection_plan", manifest)
            self.assertIn("tool_invocation_manifest", manifest)
            self.assertTrue(manifest["tools_capability_analysis"]["all_relevant_tool_types_analyzed"])
            self.assertGreaterEqual(len(manifest["tool_selection_plan"]["selected_tools"]), 6)
            self.assertTrue(manifest["shotcraft_motion_plan"]["available"])
            self.assertGreaterEqual(manifest["shotcraft_motion_plan"]["registry_count"], 100)
            self.assertTrue(cards[0]["shotcraft"]["available"])

    def test_runner_rejects_invalid_visual_recipe(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["kuaishou"],
                "visual_recipe": {
                    "template_family": "knowledge_card_motion_case",
                    "modules": ["template_theme"],
                    "selection_reason": "",
                },
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Invalid recipe"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "visual_recipe_failed")
            self.assertFalse(manifest["visual_recipe_gate"]["passed"])

    def test_runner_reselects_after_recent_duplicate_visual_recipe_core(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            first_out = Path(tmp) / "first"
            out = Path(tmp) / "out"
            registry = Path(tmp) / "visual_recipe_registry.json"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "content_form": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["kuaishou"],
                "color_mood": "clean_blueprint",
                "motion_density": "medium",
                "text_layout": "timeline_cards",
                "scene_change_interval_sec": 4,
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            first_env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(first_out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            first_proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Old topic"],
                capture_output=True,
                text=True,
                env=first_env,
                timeout=30,
                check=False,
            )
            self.assertEqual(first_proc.returncode, 0, first_proc.stderr)
            first_manifest = json.loads((first_out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            duplicate = first_manifest["visual_recipe"]
            registry.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": duplicate["core_fingerprint"],
                                "fingerprint": duplicate["fingerprint"],
                                "template_family": duplicate["template_family"],
                                "platforms": ["kuaishou"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "New topic"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "dry_run")
            self.assertTrue(manifest["recipe_reuse_gate"]["passed"])
            self.assertTrue(manifest["recipe_collision_recovery"]["recovered"])
            self.assertEqual(manifest["recipe_collision_recovery"]["attempts"][0]["duplicate_count"], 1)
            fingerprints = {row["core_fingerprint"] for row in manifest["recipe_collision_recovery"]["attempts"]}
            self.assertGreater(len(fingerprints), 1)

    def test_runner_rejects_cross_platform_same_core_visual_recipe(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            first_out = Path(tmp) / "first"
            out = Path(tmp) / "out"
            registry = Path(tmp) / "visual_recipe_registry.json"
            base_plan = {
                "selected_pipeline": "knowledge_card_video",
                "content_form": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "color_mood": "clean_blueprint",
                "motion_density": "medium_high",
                "text_layout": "split_screen_steps",
                "scene_change_interval_sec": 4,
            }
            first_plan_path = Path(tmp) / "first_plan.json"
            first_plan_path.write_text(json.dumps({**base_plan, "platforms": ["douyin"]}), encoding="utf-8")
            first_env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(first_out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(first_plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            first_proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Old topic"],
                capture_output=True,
                text=True,
                env=first_env,
                timeout=30,
                check=False,
            )
            self.assertEqual(first_proc.returncode, 0, first_proc.stderr)
            duplicate = json.loads((first_out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))["visual_recipe"]
            registry.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": duplicate["core_fingerprint"],
                                "fingerprint": duplicate["fingerprint"],
                                "template_family": duplicate["template_family"],
                                "modules": duplicate["modules"],
                                "style_variants": duplicate["style_variants"],
                                "platforms": ["douyin"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps({**base_plan, "platforms": ["youtube"]}), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "New platform topic"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "dry_run")
            self.assertTrue(manifest["recipe_reuse_gate"]["passed"])
            self.assertTrue(manifest["recipe_collision_recovery"]["recovered"])
            self.assertEqual(manifest["recipe_collision_recovery"]["attempts"][0]["duplicates"][0]["duplicate_scope"], "cross_platform")

    def test_runner_reselects_when_explicit_visual_recipe_collides(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            registry = Path(tmp) / "registry.json"
            explicit = {
                "template_family": "chaptered_explainer",
                "modules": ["template_theme", "cinema_color_css", "cinema_composition_layout"],
                "style_variants": {"color_mood": "fresh_green", "motion_density": "fast_cut", "text_layout": "large_number_story", "scene_change_interval_sec": 6},
                "asset_strategy": {"primary": "generated", "fallback": "cards", "forbidden": []},
                "selection_reason": "test",
                "differentiation_reason": "test",
                "scene_asset_match": [{"scene": i, "script_beat": f"b{i}", "visual_source": f"v{i}", "match_reason": "test"} for i in range(1, 4)],
                "avoid": ["same_recipe_fingerprint", "same_bgm_fingerprint"],
            }
            from content_platform.video_recipe import build_visual_recipe
            built = build_visual_recipe({"selected_pipeline": "article_explainer_video", "visual_recipe": explicit}, script_body="One.\nTwo.\nThree.", title="Title")
            registry.write_text(json.dumps({"recipes": [{
                "used_at": "2099-01-01T00:00:00+00:00", "core_fingerprint": built["core_fingerprint"],
                "fingerprint": built["fingerprint"], "template_family": built["template_family"],
                "modules": built["modules"], "style_variants": built["style_variants"], "platforms": ["kuaishou"],
            }]}), encoding="utf-8")
            plan = {"selected_pipeline": "article_explainer_video", "content_form": "vertical_video", "template_family": "chaptered_explainer", "platforms": ["kuaishou"], "visual_recipe": explicit}
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {**os.environ, "VIDEO_OUTPUT_DIR": str(out), "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path), "VIDEO_TOOLCHAIN_DRY_RUN": "1", "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry)}

            proc = subprocess.run([sys.executable, str(script), "One scene.\nTwo scene.\nThree scene.", "Title"], capture_output=True, text=True, env=env, timeout=30, check=False)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["recipe_collision_recovery"]["recovered"])
            self.assertNotEqual(manifest["visual_recipe"]["core_fingerprint"], built["core_fingerprint"])

    def test_localized_repost_refuses_original_card_fallback_without_source(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Do not turn this into original cards.", "Repost only"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "source_required")
            self.assertIn("refusing original card fallback", manifest["error"])

    def test_localized_repost_accepts_local_source_video_without_card_generation(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
                "source_video_path": str(source),
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Repost source.", "Repost only"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((out / "cards.json").exists())
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "rendered")
            self.assertEqual(manifest["repost_source"]["source_type"], "local_source_video")
            self.assertIn("autoclip_adapter.run_autoclip_pipeline", manifest["toolchain_contract"]["planned_tools"])
            self.assertIn("tools_capability_analysis", manifest)
            self.assertIn("tool_selection_plan", manifest)
            self.assertIn("tool_invocation_manifest", manifest)

    def test_runner_dry_run_includes_cinema_storyboard_fields(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["bilibili"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "为了省时间我装了15个AI工具。步骤一：砍掉功能重叠。", "AI工具效率"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("cinema_storyboard", manifest)
            self.assertEqual(len(manifest["cinema_storyboard"]), 8)
            first = cards[0]
            for key in ["cinema", "traffic_pattern", "composition_advice", "layout_template", "color_scheme", "css"]:
                self.assertIn(key, first)
            self.assertIn("rgba(", first["css"]["card_bg"])
            self.assertIn("rgba(", first["css"]["card_border"])

    def test_runner_dry_run_records_full_toolchain_contract(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "AI 工具太多会拖慢工作流。步骤一：先砍重复工具。", "AI工具工作流"],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,  # workflow context + recipe generation can exceed 30s under full-suite load
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            contract = manifest["toolchain_contract"]
            for tool in [
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
            ]:
                self.assertIn(tool, contract["planned_tools"])
            self.assertIn("cinema_color_css", contract["effect_stack"])
            self.assertIn("shotcraft_motion_css", contract["effect_stack"])
            self.assertGreaterEqual(contract["template_registry"]["shotcraft_registry_count"], 100)
            self.assertEqual(contract["template_registry"]["theme"], "cyber-neon")
            self.assertIn("visual_gate.py --cinema", contract["post_render_gates"])
            self.assertIn("--bgm-style", manifest["renderer_command_preview"])
            self.assertIn("--width", manifest["renderer_command_preview"])
            self.assertIn("1080", manifest["renderer_command_preview"])
            self.assertIn("--height", manifest["renderer_command_preview"])
            self.assertIn("1920", manifest["renderer_command_preview"])
            self.assertEqual(manifest["bgm_style"], contract["bgm_style"])

    def test_cinema_visual_gate_skips_auxiliary_render_layers(self):
        from scripts import video_toolchain_runner as runner

        self.assertTrue(runner._is_full_card_visual_candidate(Path("card_01.png")))
        self.assertFalse(runner._is_full_card_visual_candidate(Path("card_01_bg.png")))
        self.assertFalse(runner._is_full_card_visual_candidate(Path("card_01_text.png")))

    def test_kuaishou_layered_text_filters_are_distinct_motion_paths(self):
        from scripts import kuaishou_render as renderer

        filters = [renderer._text_layer_filter(1080, 1920, 100, idx) for idx in range(4)]
        self.assertEqual(len(set(filters)), 4)
        self.assertTrue(any("iw*1.018" in item for item in filters))
        self.assertTrue(any("min(24" in item for item in filters))
        self.assertTrue(any("max(0, 24-n*24" in item or "max(0,24" in item for item in filters))
        layered = renderer._layered_segment_filter(1080, 1920, 100, 2)
        self.assertIn("[0:v]", layered)
        self.assertIn("[1:v]", layered)
        self.assertIn("overlay=x=", layered)
        self.assertIn("eval=frame", layered)

    def test_kuaishou_background_motion_meets_artifact_gate_threshold(self):
        from scripts import kuaishou_render as renderer

        filters = [renderer._background_layer_filter(1080, 1920, 100, idx) for idx in range(4)]

        self.assertIn("0.30*on/100", filters[0])
        self.assertIn("1.45", filters[0])
        self.assertIn("0.30*on/100", filters[1])
        self.assertIn("sin(on/30)*80", filters[2])
        self.assertIn("cos(on/30)*80", filters[3])

    def test_runner_passes_target_platform_to_shared_subtitle_renderer(self):
        from scripts.video_toolchain_runner import _renderer_command

        command = _renderer_command(
            Path("/tmp/renderer.py"),
            Path("/tmp/out"),
            "blueprint",
            "Video title",
            "A useful script.",
            {"platforms": ["shipinhao"]},
            "light piano",
        )

        self.assertIn("--platform", command)
        self.assertEqual(command[command.index("--platform") + 1], "shipinhao")

    def test_landscape_renderer_uses_separate_background_and_text_layers(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "render_landscape_video.py").read_text(encoding="utf-8")

        self.assertIn("slide_{idx:02d}_bg.html", source)
        self.assertIn("slide_{idx:02d}_text.html", source)
        self.assertIn("card_{idx:02d}_bg.png", source)
        self.assertIn("card_{idx:02d}_text.png", source)
        self.assertIn("zoompan=", source)
        self.assertIn("overlay=0:0:format=auto", source)

    def test_runner_dry_run_records_shotcraft_motion_plan(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "AI tools can slow teams down.\n\nUse one tool per workflow stage.\n\nEnd with a clear rule.",
                    "AI tool workflow rules",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            shotcraft = manifest["shotcraft_motion_plan"]
            self.assertTrue(shotcraft["available"])
            self.assertGreaterEqual(shotcraft["registry_count"], 100)
            self.assertGreaterEqual(len(shotcraft["selected_shots"]), 3)
            self.assertGreaterEqual(len(shotcraft["timeline"]), 3)
            self.assertEqual(cards[0]["shotcraft"]["name"], shotcraft["timeline"][0]["name"])

    def test_runner_accepts_bom_prefixed_plan_json(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text("\ufeff" + json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "One useful script beat.\n\nAnother visual beat.", "BOM plan"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["shotcraft_motion_plan"]["available"])

    def test_intl_short_video_defaults_to_project_toolchain_before_legacy_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "intl_short_video_pipeline.py").read_text(encoding="utf-8")

        self.assertLess(source.index("_gen_with_project_toolchain"), source.index("screencast_engine.py"))
        self.assertIn("INTL_VIDEO_ALLOW_LEGACY_FALLBACK", source)
        self.assertIn("video_toolchain_runner.py", source)

    def test_renderer_html_consumes_cinema_css_when_background_image_is_absent(self):
        from scripts.kuaishou_render import THEMES, build_card_html

        html = build_card_html(
            {
                "layout": "cover",
                "hook": "AI工具工作流",
                "sub": "减少维护成本",
                "css": {
                    "bg_gradient": "linear-gradient(135deg, rgb(30, 35, 45) 0%, rgb(55, 65, 80) 100%)",
                    "accent_color": "rgb(62, 207, 135)",
                    "text_primary": "#ffffff",
                    "card_bg": "rgba(55,65,80,0.85)",
                },
            },
            1,
            None,
            None,
            THEMES["cyber-neon"],
        )

        self.assertIn("linear-gradient(135deg, rgb(30, 35, 45)", html)
        self.assertIn("repeating-linear-gradient", html)
        self.assertIn("rgb(62, 207, 135)", html)

    def test_renderer_video_assertion_uses_ffprobe_when_size_is_below_legacy_threshold(self):
        from scripts.kuaishou_render import assert_output

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "short.mp4"
            video.write_bytes(b"0" * 80_000)

            fake = type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "streams": [{"codec_type": "video", "width": 720, "height": 1280}],
                            "format": {"duration": "12.5", "size": "80000"},
                        }
                    ),
                    "stderr": "",
                },
            )()
            with patch("scripts.kuaishou_render.subprocess.run", return_value=fake):
                assert_output(str(video), 2_000_000, "short.mp4")

    def test_bgm_download_uses_online_real_instrument_candidate(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            (root / "raw.mp4").write_bytes(b"0" * 900_000)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic-guitar.mp3",
                "source_url": "https://pixabay.com/music/acoustic-guitar",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "Pixabay Content License",
                "attribution_required": False,
                "duration": 90,
                "asset_id": "px1",
                "tags": "acoustic guitar instrumental folk",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(b"1" * 900_000)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        bgm = download_bgm(root, "acoustic guitar")

            self.assertEqual(Path(bgm), root / "bgm.mp3")
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "pixabay_music")
            self.assertEqual(source["license"], "Pixabay Content License")
            self.assertTrue(source["sha256"])
            registry_data = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(registry_data["tracks"][0]["fingerprint"], source["sha256"])

    def test_bgm_download_rejects_registry_duplicate_fingerprint(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            duplicate_bytes = b"1" * 900_000
            duplicate_hash = __import__("hashlib").sha256(duplicate_bytes).hexdigest()
            registry.write_text(json.dumps({"tracks": [{"fingerprint": duplicate_hash, "title": "used"}]}), encoding="utf-8")
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic-guitar.mp3",
                "source_url": "https://pixabay.com/music/acoustic-guitar",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "Pixabay Content License",
                "attribution_required": False,
                "duration": 90,
                "asset_id": "px1",
                "tags": "acoustic guitar instrumental folk",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(duplicate_bytes)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        with self.assertRaisesRegex(RuntimeError, "BGM fingerprint already used"):
                            download_bgm(root, "acoustic guitar")

            self.assertFalse((root / "bgm_source.json").exists())

    def test_bgm_download_replaces_stale_existing_bgm_every_render(self):
        from scripts.kuaishou_render import download_bgm, REAL_BGM_MIN_BYTES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            (root / "bgm.mp3").write_bytes(b"old" * (REAL_BGM_MIN_BYTES // 3))
            (root / "bgm_source.json").write_text(
                json.dumps({"source": "local_instrument_bgm_library", "license": "operator_provided"}),
                encoding="utf-8",
            )
            candidate = {
                "provider": "openverse_audio",
                "download_url": "https://cdn.example/acoustic.mp3",
                "source_url": "https://freesound.example/sounds/1",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "https://creativecommons.org/licenses/by/4.0/",
                "attribution_required": True,
                "duration": 90,
                "asset_id": "ov1",
                "tags": "acoustic guitar instrumental",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(b"new" * 300_000)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        download_bgm(root, "acoustic guitar")

            self.assertEqual((root / "bgm.mp3").read_bytes(), b"new" * 300_000)
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "openverse_audio")

    def test_bgm_download_reuses_valid_existing_bgm(self):
        from scripts.kuaishou_render import download_bgm, REAL_BGM_MIN_BYTES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bgm.mp3").write_bytes(b"x" * (REAL_BGM_MIN_BYTES + 1000))
            (root / "bgm_source.json").write_text(
                json.dumps({
                    "source": "openverse_audio", "license": "cc0", "title": "acoustic guitar instrumental",
                    "source_url": "https://openverse.org/audio/example", "fit_reason": "real acoustic guitar match",
                }),
                encoding="utf-8",
            )
            with patch("scripts.kuaishou_render._media_duration", return_value=61.0), patch("scripts.kuaishou_render._online_bgm_candidates") as mock_online:
                result = download_bgm(root, "acoustic guitar")
            mock_online.assert_not_called()
            self.assertEqual(result, str(root / "bgm.mp3"))

    def test_bgm_download_refuses_synthetic_or_no_bgm_fallback(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"0" * 80_000)

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "online real-instrument BGM unavailable"):
                    download_bgm(root, "lo-fi")

    def test_bgm_download_does_not_use_operator_local_library(self):
        from scripts.kuaishou_render import REAL_BGM_MIN_BYTES, download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library" / "track-a"
            library.mkdir(parents=True)
            (library / "bgm.mp3").write_bytes(b"licensed" * (REAL_BGM_MIN_BYTES // 8 + 1))
            (library / "bgm_manifest.json").write_text(
                json.dumps({
                    "title": "Licensed piano",
                    "artist": "Artist",
                    "license": "CC BY",
                    "source_url": "https://example.test/license",
                    "provider": "local_test_library",
                    "style": "piano instrumental",
                }),
                encoding="utf-8",
            )
            registry = root / "fingerprints.json"
            with patch.dict(os.environ, {
                "BGM_LIBRARY_DIR": str(root / "library"),
                "BGM_FINGERPRINT_REGISTRY": str(registry),
            }, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[]):
                    with self.assertRaisesRegex(RuntimeError, "online real-instrument BGM unavailable"):
                        download_bgm(root, "piano instrumental")

            self.assertFalse((root / "bgm_source.json").exists())

    def test_bgm_download_stops_when_the_global_resolution_budget_is_exhausted(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic.mp3",
                "source_url": "https://pixabay.example/acoustic",
                "title": "Acoustic guitar instrumental",
                "license": "Pixabay Content License",
                "tags": "acoustic guitar instrumental",
            }
            with patch.dict(os.environ, {"BGM_RESOLUTION_MAX_SECONDS": "1"}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render.time.monotonic", side_effect=[0.0, 2.0]):
                        with self.assertRaisesRegex(RuntimeError, "resolution budget exhausted"):
                            download_bgm(root, "acoustic guitar")

    def test_openverse_candidates_skip_short_sound_effects(self):
        from scripts.kuaishou_render import _openverse_candidates

        payload = {
            "results": [
                {"id": "short", "title": "Piano tap", "url": "https://cdn.test/short.mp3", "foreign_landing_url": "https://source.test/short", "license": "cc0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/", "duration": 4000, "tags": [{"name": "piano"}]},
                {"id": "long", "title": "Piano performance", "url": "https://cdn.test/long.mp3", "foreign_landing_url": "https://source.test/long", "license": "cc0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/", "duration": 78000, "tags": [{"name": "piano"}]},
            ]
        }
        with patch("scripts.kuaishou_render._request_json", return_value=payload):
            rows = _openverse_candidates("piano music instrumental")

        self.assertEqual([row["asset_id"] for row in rows], ["long"])
        self.assertEqual(rows[0]["duration"], 78)

    def test_bgm_queries_prioritize_requested_instrument(self):
        from scripts.kuaishou_render import _bgm_queries

        piano = _bgm_queries("upright piano and brushed drums")
        guitar = _bgm_queries("warm acoustic guitar")

        self.assertIn("piano", piano[0])
        self.assertNotIn("guitar", piano[0])
        self.assertIn("guitar", guitar[0])

    def test_fallback_backgrounds_merge_without_dropping_existing_provenance(self):
        from scripts.video_toolchain_runner import _asset_provenance_records, _merge_materialized_backgrounds

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.png"
            second = root / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            existing = [{
                "scene": 1, "path": str(first), "source_url": "generated:image-provider",
                "license": "generated_for_project", "semantic_match_score": 0.82,
                "match_reason": "cover match", "semantic_tags": ["cover"],
                "generation_evidence": {"provider": "image-provider"},
            }]
            additions = [{
                "background_image": str(second), "source_url": "https://www.pexels.com/photo/1/",
                "license": "Pexels Content License", "semantic_match_score": 0.8,
                "source_query": "technology office", "semantic_tags": ["technology"],
            }]

            merged = _merge_materialized_backgrounds(existing, additions)
            records = _asset_provenance_records(merged)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["source_url"], "generated:image-provider")
            self.assertEqual(records[1]["source_url"], "https://www.pexels.com/photo/1/")
            self.assertEqual(records[1]["license"], "Pexels Content License")

    def test_materialized_assets_become_the_manifest_and_card_assignments(self):
        from scripts.video_toolchain_runner import _visual_assets_from_materialized

        materialized = [
            {"scene": index, "path": f"/tmp/bg-{index}.jpg", "source_url": f"https://pexels.test/{index}", "license": "Pexels Content License", "semantic_match_score": 0.8, "match_reason": "matched", "semantic_tags": ["tech"]}
            for index in range(1, 9)
        ]
        packet = _visual_assets_from_materialized(materialized)

        self.assertEqual(packet["scene_count"], 8)
        self.assertEqual(len(packet["assignments"]), 8)
        self.assertEqual(packet["assignments"][0]["background_image"], "/tmp/bg-1.jpg")
        self.assertEqual(packet["assignments"][0]["source_url"], "https://pexels.test/1")

    def test_bgm_download_rejects_electronic_synthetic_candidates(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/synth.mp3",
                "source_url": "https://pixabay.com/music/synth",
                "title": "Electronic synth lofi beat",
                "artist": "artist",
                "license": "Pixabay Content License",
                "tags": "electronic synth instrumental",
            }

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                with self.assertRaisesRegex(RuntimeError, "no licensed real-instrument candidates"):
                    download_bgm(root, "electronic")

    def test_openverse_candidates_require_commercial_safe_license(self):
        from scripts.kuaishou_render import _openverse_candidates

        payload = {
            "results": [
                {
                    "id": "ok",
                    "title": "Acoustic guitar instrumental",
                    "creator": "artist",
                    "url": "https://cdn.example/ok.mp3",
                    "foreign_landing_url": "https://example.test/ok",
                    "license": "by",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "duration": 90000,
                    "audio_set": {"title": "Acoustic guitar"},
                    "tags": [{"name": "guitar"}],
                },
                {
                    "id": "blocked",
                    "title": "Acoustic guitar nc",
                    "creator": "artist",
                    "url": "https://cdn.example/nc.mp3",
                    "foreign_landing_url": "https://example.test/nc",
                    "license": "by-nc",
                    "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                },
            ]
        }

        with patch("scripts.kuaishou_render._request_json", return_value=payload):
            rows = _openverse_candidates("acoustic guitar instrumental")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "openverse_audio")
        self.assertEqual(rows[0]["duration"], 90)
        self.assertTrue(rows[0]["license_verified"])

    def test_youtube_audio_library_candidates_are_youtube_scoped(self):
        from scripts.kuaishou_render import _bgm_candidate_allowed, _youtube_audio_library_candidates

        payload = {
            "all": [
                {"id": "drive-id", "name": "Acoustic_Guitar_Story.mp3", "mimeType": "audio/mpeg"},
                {"id": "blocked-id", "name": "Digital_Synth_Pulse.mp3", "mimeType": "audio/mpeg"},
            ],
            "map": {"drive-id": "https://docs.google.com/uc?export=open&id=drive-id"},
        }

        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "youtube"}, clear=False):
            with patch("scripts.kuaishou_render._request_json", return_value=payload):
                rows = _youtube_audio_library_candidates("acoustic guitar instrumental")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "youtube_audio_library")
        self.assertEqual(rows[0]["license_scope"], "youtube_only")
        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "youtube"}, clear=False):
            self.assertTrue(_bgm_candidate_allowed(rows[0]))
        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "kuaishou"}, clear=False):
            self.assertFalse(_bgm_candidate_allowed(rows[0]))

    def test_subtitles_are_wrapped_and_kept_above_bottom_safe_area(self):
        from scripts.kuaishou_render import gen_subtitles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tts = root / "tts"
            tts.mkdir()
            (tts / "tts_01.mp3").write_bytes(b"0")

            def fake_run(command, **kwargs):
                return type("Result", (), {"returncode": 0, "stdout": "5.0", "stderr": ""})()

            cards = [{"tts": "这是一条非常长的字幕内容必须自动换行不能超过视频宽度否则就会贴边"}]
            with patch("scripts.kuaishou_render.subprocess.run", side_effect=fake_run):
                gen_subtitles(root, cards)

            ass = (root / "subtitles.ass").read_text(encoding="utf-8")
            self.assertIn("20,20,200", ass)
            self.assertIn(r"\N", ass)

    def test_card_html_uses_sub_as_center_body_when_txt_missing(self):
        from scripts.kuaishou_render import build_card_html

        html = build_card_html(
            {"layout": "two_column", "t": "Title", "sub": "center body from sub"},
            1,
            "",
            "",
            {"accent": "#fff", "accent2": "#eee", "bg": "000", "text": "#ddd", "card_bg": "rgba(0,0,0,.2)", "badge_bg": "rgba(0,0,0,.2)", "glass": "rgba(0,0,0,.2)"},
        )
        self.assertIn("center body from sub", html)

    def test_packet_schedule_slot_tolerates_non_numeric_working_directory(self):
        from scripts.kuaishou_render import _safe_schedule_slot

        self.assertEqual(_safe_schedule_slot("video_toolchain_real_contract_verify"), 0)
        self.assertEqual(_safe_schedule_slot("job_7"), 7)

    def test_legacy_video_generation_demos_are_fail_closed_by_default(self):
        root = Path(__file__).resolve().parents[1]
        guarded = [
            "scripts/animated_card_pipeline.py",
            "scripts/knowledge_card_demo.py",
            "scripts/kuaishou_final_pipeline.py",
            "scripts/render_animation.py",
            "scripts/douyin_cat_cards.py",
        ]
        for rel in guarded:
            source = (root / rel).read_text(encoding="utf-8")
            self.assertIn("raise SystemExit", source, rel)
        kuaishou_legacy = (root / "scripts/kuaishou_final_pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("SoundHelix", kuaishou_legacy)
        self.assertNotIn("bgm_test", kuaishou_legacy)
        self.assertNotIn("HERMES_ALLOW_LEGACY_RENDER_DEMO", kuaishou_legacy)


if __name__ == "__main__":
    unittest.main()
