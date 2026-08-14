import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.tool_catalog import catalog_snapshot
from content_platform.tool_selection import build_tools_capability_analysis
from content_platform.theme_registry import select_theme
from scripts.kuaishou_render import _layered_segment_filter, _shotcraft_motion_profile, build_card_html
from scripts.video_toolchain_runner import _render_motion_evidence


class ToolCatalogAndMotionTests(unittest.TestCase):
    def test_catalog_separates_runtime_and_deferred_capabilities(self):
        snapshot = catalog_snapshot()
        self.assertEqual(snapshot["version"], "tool_catalog_v1")
        self.assertEqual(snapshot["tools"]["moneyprinterturbo"]["decision"], "do_not_integrate")
        self.assertEqual(snapshot["tools"]["video_shotcraft"]["decision"], "extract_patterns")

    def test_capability_analysis_carries_catalog(self):
        result = build_tools_capability_analysis(platform="kuaishou", content_type="video")
        self.assertIn("tool_catalog", result)
        self.assertTrue(result["tool_catalog"]["tools"]["openmontage"])

    def test_card_html_contains_selected_shotcraft_recipe(self):
        html = build_card_html(
            {"layout": "cover", "t": "Hook", "sub": "Body", "shotcraft": {"name": "hero-card"}},
            1,
            None,
            None,
            {"accent": "#fff", "accent2": "#000", "text": "#fff", "card_bg": "#000", "badge_bg": "#000", "glass": "#000", "bg": "000"},
        )
        self.assertIn("data-shotcraft=\"hero-card\"", html)
        self.assertIn("@keyframes", html)

    def test_theme_selection_uses_verified_wechat_theme_not_an_unbounded_template_pool(self):
        selection = select_theme("wechat", "AI workflow tutorial", "guide")
        self.assertEqual(selection["selected"], "wechat_practical")
        self.assertIn(selection["selected"], selection["candidates"])

    def test_layered_renderer_uses_the_selected_shot_profile(self):
        hero = _layered_segment_filter(1080, 1920, 100, 0, shotcraft={"name": "hero-card"})
        timeline = _layered_segment_filter(1080, 1920, 100, 0, shotcraft={"name": "timeline"})
        self.assertIn("zoompan", hero)
        self.assertEqual(_shotcraft_motion_profile({"name": "hero-card"}), "hero_reveal")
        self.assertEqual(_shotcraft_motion_profile({"name": "timeline"}), "data_pan")
        self.assertNotEqual(hero, timeline)

    @patch("scripts.video_toolchain_runner.subprocess.run")
    def test_motion_evidence_requires_distinct_frames(self, run):
        def fake(args, **kwargs):
            if args[0] == "ffprobe":
                return type("Result", (), {"stdout": "10", "stderr": "", "returncode": 0})()
            offset = args[args.index("-ss") + 1]
            payload = ("frame-" + offset).encode()
            return type("Result", (), {"stdout": payload, "stderr": "", "returncode": 0})()

        run.side_effect = fake
        result = _render_motion_evidence(Path("/tmp/final.mp4"))
        self.assertTrue(result["passed"])
        self.assertEqual(result["unique_frame_count"], 5)


if __name__ == "__main__":
    unittest.main()
