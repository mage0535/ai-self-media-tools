import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class VideoToolchainRunnerTests(unittest.TestCase):
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
            self.assertTrue(manifest["shotcraft_motion_plan"]["available"])
            self.assertGreaterEqual(manifest["shotcraft_motion_plan"]["registry_count"], 100)
            self.assertTrue(cards[0]["shotcraft"]["available"])

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
                timeout=30,
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
            self.assertEqual(manifest["bgm_style"], contract["bgm_style"])

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

    def test_bgm_download_falls_back_to_generated_synthetic_audio(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"0" * 80_000)

            def fake_run(command, **kwargs):
                if command[0] == "ffprobe":
                    return type("Result", (), {"returncode": 0, "stdout": "12.0", "stderr": ""})()
                if command[0] == "ffmpeg":
                    (root / "bgm.mp3").write_bytes(b"1" * 80_000)
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "network unavailable"})()

            with patch("scripts.kuaishou_render.subprocess.run", side_effect=fake_run):
                bgm = download_bgm(root, "lo-fi")

            self.assertEqual(Path(bgm), root / "bgm.mp3")
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "generated_synthetic_bgm")

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
            self.assertIn("HERMES_ALLOW_LEGACY_RENDER_DEMO", source, rel)
            self.assertIn("raise SystemExit", source, rel)


if __name__ == "__main__":
    unittest.main()
