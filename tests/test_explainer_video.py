import json
import tempfile
import unittest
from pathlib import Path

from content_platform.explainer_video import build_explainer_storyboard, write_explainer_package


class ExplainerVideoTests(unittest.TestCase):
    def test_build_explainer_storyboard_includes_video_toolchain_contract(self):
        article = "# AI工具使用规则\n\n很多人装了很多工具，但效率没有提升。\n\n先砍掉重叠工具，再给每个工具一个唯一用途。"

        package = build_explainer_storyboard(article, target_pages=6)

        self.assertTrue(package["ok"])
        self.assertEqual(package["content_form"], "article_explainer_video")
        self.assertGreaterEqual(len(package["pages"]), 4)
        self.assertIn("narration_script", package)
        self.assertTrue(package["quality_contract"]["requires_real_instrument_bgm"])
        plan = package["video_toolchain_plan"]
        self.assertTrue(plan["required"])
        self.assertEqual(plan["selected_pipeline"], "article_explainer_video")
        self.assertEqual(plan["template_family"], "chaptered_explainer")
        self.assertIn("article_explainer_planner", plan["required_tools"])
        self.assertIn("shotcraft_motion_designer", plan["required_tools"])
        self.assertIn("licensed_background_music", plan["quality_gates"])

    def test_write_explainer_package_outputs_runner_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article = root / "article.md"
            article.write_text("# 选题标题\n\n第一段解释问题。\n\n第二段给出方法。\n\n第三段总结行动。", encoding="utf-8")

            result = write_explainer_package(article, root / "out", target_pages=5, presenter_side="left")

            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["storyboard"]).is_file())
            self.assertTrue(Path(result["slides"]).is_file())
            self.assertTrue(Path(result["video_toolchain_plan"]).is_file())
            self.assertTrue(Path(result["image_prompts"]).is_file())
            prompts = json.loads(Path(result["image_prompts"]).read_text(encoding="utf-8"))
            self.assertEqual(len(prompts), result["pages"])
            self.assertEqual(prompts[0]["role"], "cover")


if __name__ == "__main__":
    unittest.main()
