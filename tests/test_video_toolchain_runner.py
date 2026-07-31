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

    def test_bgm_download_uses_online_real_instrument_candidate(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"0" * 80_000)
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
                output.write_bytes(b"1" * 80_000)

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                    bgm = download_bgm(root, "acoustic guitar")

            self.assertEqual(Path(bgm), root / "bgm.mp3")
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "pixabay_music")
            self.assertEqual(source["license"], "Pixabay Content License")
            self.assertTrue(source["sha256"])

    def test_bgm_download_replaces_stale_existing_bgm_every_render(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bgm.mp3").write_bytes(b"old" * 30_000)
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
                output.write_bytes(b"new" * 30_000)

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                    download_bgm(root, "acoustic guitar")

            self.assertEqual((root / "bgm.mp3").read_bytes(), b"new" * 30_000)
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "openverse_audio")

    def test_bgm_download_refuses_synthetic_or_no_bgm_fallback(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"0" * 80_000)

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "online real-instrument BGM unavailable"):
                    download_bgm(root, "lo-fi")

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
