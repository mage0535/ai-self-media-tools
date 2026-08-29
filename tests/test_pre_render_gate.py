import json
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch


class PreRenderGateTests(unittest.TestCase):
    def test_gate_blocks_full_narration_duplicated_in_card_text(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            narration = "完整讲解只应该出现在字幕，不应该在卡片正文重复。"
            cards = [{"layout": "cover", "t": "核心结论", "txt": narration, "tts": narration, "items": []}]

            result = validate_render_inputs(root, cards, require_backgrounds=False, require_cover_contract=True)

            self.assertIn("card_1_narration_display_duplicate", result["failures"])

    def test_gate_blocks_placeholder_card_content_before_render(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"background")
            cards = [{"layout": "cover", "t": "Useful title", "txt": "Step 1: keep the visual rhythm", "tts": "Step 1: keep the visual rhythm", "items": ["Step 1"]}]

            result = validate_render_inputs(root, cards, require_cover_contract=True)

            self.assertFalse(result["passed"])
            self.assertTrue(any("placeholder" in item for item in result["failures"]))

    def test_gate_accepts_low_bgm_as_auto_gain_candidate_not_failure(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"background")
            cards = [{"layout": "cover", "t": "Useful title", "txt": "Core problem", "tts": "A complete spoken explanation of the real script beat.", "items": ["Useful point"]}]
            bgm = root / "bgm.mp3"
            bgm.write_bytes(b"licensed music")
            (root / "bgm_source.json").write_text(
                '{"source":"pixabay_music","license":"Pixabay Content License","sha256":"new-track"}',
                encoding="utf-8",
            )

            result = validate_render_inputs(root, cards, bgm_mean_volume_db=-39.5, require_cover_contract=True)

            self.assertTrue(result["passed"])
            self.assertIn("bgm_requires_auto_gain", result["warnings"])

    def test_gate_requires_scene_manifest_when_requested(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"background")
            cards = [{"layout": "cover", "t": "Useful title", "txt": "A real script beat", "tts": "A real script beat", "items": ["A useful point"]}]

            result = validate_render_inputs(root, cards, require_scene_manifest=True, require_backgrounds=False)

            self.assertFalse(result["passed"])
            self.assertIn("scene_manifest_missing", result["failures"])

    def test_gate_rejects_scene_manifest_without_six_layered_scenes(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"background")
            (root / "scene_manifest.json").write_text('{"scenes":[{}]}', encoding="utf-8")
            cards = [{"layout": "cover", "t": "Useful title", "txt": "A real script beat", "tts": "A real script beat", "items": ["A useful point"]}]

            result = validate_render_inputs(root, cards, require_scene_manifest=True)

            self.assertFalse(result["passed"])
            self.assertIn("scene_manifest_invalid", result["failures"])

    def test_gate_accepts_the_canonical_scene_manifest_contract(self):
        from scripts.pre_render_gate import validate_render_inputs
        from content_platform.scene_manifest import build_scene_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards = [
                {"layout": "cover" if index == 0 else "card", "t": f"Title {index}", "txt": f"Key point {index}", "tts": f"A complete spoken explanation for scene number {index}."}
                for index in range(6)
            ]
            recipe = {
                "fingerprint": "recipe-1",
                "scene_asset_match": [
                    {"visual_source": f"planned_asset_{index}", "match_reason": f"matches beat {index}"}
                    for index in range(6)
                ],
            }
            manifest = build_scene_manifest(cards, recipe, {"platforms": ["douyin"]}, "Useful title")
            (root / "scene_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_render_inputs(root, cards, require_scene_manifest=True, require_backgrounds=False)

            self.assertTrue(result["passed"])

    def test_mascots_are_functional_work_level_requirement_not_scene_wide(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards = [{"layout": "cover", "t": "AI workflow"}, {"t": "evidence"}, {"t": "result"}]
            manifest = {
                "version": "scene_manifest_v2",
                "mascot_roles": {"cat": {"narrative_function": "introduce the problem", "decorative_only": False}},
                "scenes": [],
            }
            (root / "scene_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_render_inputs(root, cards, require_backgrounds=False, require_scene_manifest=True, require_functional_mascots=True)
            self.assertIn("scene_manifest_invalid", result["failures"])
            self.assertNotIn("functional_mascot_role_missing", result["failures"])

    def test_mascot_requirement_fails_without_functional_role(self):
        from scripts.pre_render_gate import validate_render_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards = [{"layout": "cover", "t": "AI workflow"}, {"t": "evidence"}, {"t": "result"}]
            (root / "scene_manifest.json").write_text(json.dumps({"version": "scene_manifest_v2", "scenes": [], "timeline": []}), encoding="utf-8")
            result = validate_render_inputs(root, cards, require_backgrounds=False, require_scene_manifest=True, require_functional_mascots=True)
            self.assertIn("functional_mascot_role_missing", result["failures"])

    def test_subtitle_builder_uses_dot_timestamps_and_safe_wrapping(self):
        from scripts.build_subtitles import build_ass

        text = "这是一段很长的字幕内容，需要在移动端安全区域内自动换行，并且不能超出画面范围。"
        ass = build_ass([(0.0, 3.25, text)], platform="douyin")

        self.assertIn("PlayResX: 720", ass)
        self.assertIn("Dialogue: 0,00:00:00.000", ass)
        self.assertIn("00:00:03.250", ass)
        self.assertIn(r"\N", ass)
        self.assertIn("MarginV", ass)

    def test_subtitle_builder_splits_long_narration_without_ellipsis(self):
        from scripts.build_subtitles import build_ass

        text = "第一段解释为什么工具切换会浪费时间，第二段说明如何把能力接入统一工作流，第三段给出验证结果和下一步行动。"
        ass = build_ass([(0.0, 8.0, text)], platform="kuaishou")

        self.assertGreaterEqual(ass.count("Dialogue:"), 2)
        self.assertNotIn("...", ass)
        self.assertIn("下一步行动", ass)

    def test_kuaishou_renderer_writes_pre_render_evidence_before_rendering(self):
        from scripts.kuaishou_render import run_pre_render_gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backgrounds").mkdir()
            (root / "backgrounds" / "bg_01.jpg").write_bytes(b"background")
            cards = [{"layout": "cover", "t": "Useful title", "txt": "Core problem", "tts": "A complete spoken explanation of the real script beat.", "items": ["Useful point"]}]

            result = run_pre_render_gate(root, cards)

            self.assertTrue(result["passed"])
            self.assertTrue((root / "pre_render_gate.json").is_file())

    def test_checkpoint_reuses_only_matching_inputs_and_adopts_legacy_done(self):
        from scripts.render_checkpoint import mark_complete, stage_current_or_adopt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "final.mp4"
            output.write_bytes(b"final")

            self.assertFalse(stage_current_or_adopt(root, "final", {"script": "v1"}, [output])["current"])
            mark_complete(root, "final", {"script": "v1"}, [output])
            self.assertTrue(stage_current_or_adopt(root, "final", {"script": "v1"}, [output])["current"])
            self.assertFalse(stage_current_or_adopt(root, "final", {"script": "v2"}, [output])["current"])

            legacy = root / "cards.done"
            legacy.write_text("ok", encoding="utf-8")
            card = root / "cards" / "card_01.png"
            card.parent.mkdir()
            card.write_bytes(b"card")
            adopted = stage_current_or_adopt(root, "cards", {"card": "v1"}, [card])
            self.assertTrue(adopted["current"])
            self.assertEqual(adopted["reason"], "legacy_done_adopted")

    def test_segment_renderer_skips_a_segment_with_matching_checkpoint(self):
        from scripts.kuaishou_render import _segment_checkpoint_inputs, render_segments
        from scripts.render_checkpoint import mark_complete

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards_dir = root / "cards"
            tts_dir = root / "tts"
            segments_dir = root / "segments"
            cards_dir.mkdir()
            tts_dir.mkdir()
            segments_dir.mkdir()
            card = {"layout": "cover", "t": "Useful title", "txt": "A real script beat", "tts": "A real script beat"}
            for name in ["card_01.png", "card_01_bg.png", "card_01_text.png"]:
                (cards_dir / name).write_bytes(b"image")
            (tts_dir / "tts_01.mp3").write_bytes(b"audio")
            segment = segments_dir / "seg_01.mp4"
            segment.write_bytes(b"segment")
            mark_complete(root, "segment_01", _segment_checkpoint_inputs(root, card, 1, 1080, 1920), [segment])

            with patch("scripts.kuaishou_render.subprocess.run") as run:
                result = render_segments(root, [card], 1080, 1920)

            run.assert_not_called()
            self.assertEqual(result, {"rendered": 0, "reused": 1})

    def test_checkpoint_adopts_a_shared_legacy_marker_for_per_item_stages(self):
        from scripts.render_checkpoint import stage_current_or_adopt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "tts" / "tts_01.mp3"
            output.parent.mkdir()
            output.write_bytes(b"voice")
            (root / "tts.done").write_text("ok", encoding="utf-8")

            result = stage_current_or_adopt(root, "tts_01", {"text": "same"}, [output], legacy_marker="tts.done")

            self.assertTrue(result["current"])
            self.assertEqual(result["reason"], "legacy_done_adopted")

    def test_card_renderer_does_not_start_browser_when_card_checkpoints_match(self):
        from scripts.kuaishou_render import THEMES, render_cards

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards_dir = root / "cards"
            backgrounds = root / "backgrounds"
            cards_dir.mkdir()
            backgrounds.mkdir()
            card = {"layout": "cover", "t": "Useful title", "txt": "A real script beat", "tts": "A real script beat", "items": ["A useful point"]}
            for name in ["card_01.png", "card_01_bg.png", "card_01_text.png"]:
                (cards_dir / name).write_bytes(b"card-layer")
            (root / "cards.done").write_text("ok", encoding="utf-8")

            with patch("scripts.kuaishou_render.async_playwright") as browser:
                result = asyncio.run(render_cards(root, [card], THEMES["blueprint"], backgrounds, None))

            browser.assert_not_called()
            self.assertEqual(result, {"rendered": 0, "reused": 1})

    def test_card_renderer_waits_for_fonts_and_images_instead_of_fixed_sleep(self):
        from scripts.kuaishou_render import _wait_for_card_assets

        class Page:
            def __init__(self):
                self.calls = []

            async def wait_for_function(self, expression, timeout):
                self.calls.append((expression, timeout))

        page = Page()
        asyncio.run(_wait_for_card_assets(page))

        self.assertEqual(len(page.calls), 1)
        expression, timeout = page.calls[0]
        self.assertIn("document.fonts.ready", expression)
        self.assertIn("naturalWidth", expression)
        self.assertEqual(timeout, 5000)

    def test_subtitle_cli_accepts_utf8_bom_card_files(self):
        from scripts.build_subtitles import load_cards

        with tempfile.TemporaryDirectory() as tmp:
            cards_path = Path(tmp) / "cards.json"
            cards_path.write_text('[{"tts":"A real subtitle"}]', encoding="utf-8-sig")

            self.assertEqual(load_cards(cards_path)[0]["tts"], "A real subtitle")

    def test_render_timing_records_cached_and_rendered_stages(self):
        from scripts.render_timing import load_timing_summary, record_stage_timing, write_timing_summary

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_stage_timing(root, "cards", 1.25, cached=False)
            record_stage_timing(root, "segments", 0.05, cached=True)

            summary = load_timing_summary(root)
            self.assertEqual(summary["stage_count"], 2)
            self.assertEqual(summary["slowest"][0]["stage"], "cards")
            self.assertTrue(summary["slowest"][1]["cached"])
            self.assertTrue(write_timing_summary(root).is_file())

    def test_final_encoder_defaults_to_fast_and_rejects_unknown_presets(self):
        from scripts.kuaishou_render import final_encode_settings

        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(final_encode_settings()["preset"], "fast")
        with patch.dict("os.environ", {"VIDEO_FINAL_PRESET": "medium"}, clear=False):
            self.assertEqual(final_encode_settings()["preset"], "medium")
        with patch.dict("os.environ", {"VIDEO_FINAL_PRESET": "not-a-preset"}, clear=False):
            with self.assertRaises(ValueError):
                final_encode_settings()

    def test_final_render_decision_uses_checkpoint_not_legacy_marker(self):
        from scripts.kuaishou_render import final_render_required

        self.assertFalse(final_render_required({"current": True, "reason": "checkpoint_match"}))
        self.assertTrue(final_render_required({"current": False, "reason": "inputs_changed"}))

    def test_kuaishou_main_reader_accepts_utf8_bom_cards(self):
        from scripts.kuaishou_render import read_cards

        with tempfile.TemporaryDirectory() as tmp:
            cards_path = Path(tmp) / "cards.json"
            cards_path.write_text('[{"tts":"A real subtitle"}]', encoding="utf-8-sig")

            self.assertEqual(read_cards(cards_path)[0]["tts"], "A real subtitle")
