import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DouyinAccountVariantsTests(unittest.TestCase):
    def setUp(self):
        self.rulebook = json.loads((ROOT / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))

    def test_douyin_accounts_are_explicitly_separated(self):
        variants = self.rulebook.get("platform_account_variants", {}).get("douyin", {})
        accounts = variants.get("accounts", {})

        self.assertEqual(variants.get("base_platform"), "douyin")
        self.assertEqual(set(variants.get("execution_order", [])), {"douyin_pet", "douyin_ai"})
        self.assertEqual(set(accounts), {"douyin_pet", "douyin_ai"})

        pet = accounts["douyin_pet"]
        ai = accounts["douyin_ai"]

        self.assertEqual(pet.get("lane"), "pet_healing")
        self.assertEqual(ai.get("lane"), "ai_efficiency_open_source")
        self.assertNotEqual(pet.get("growth_strategy_key"), ai.get("growth_strategy_key"))
        self.assertNotEqual(pet.get("cookie_account"), ai.get("cookie_account"))
        self.assertIn("douyin_pet", pet.get("output_dir_pattern", ""))
        self.assertIn("douyin_ai", ai.get("output_dir_pattern", ""))

    def test_douyin_account_variants_require_cross_account_isolation(self):
        variants = self.rulebook.get("platform_account_variants", {}).get("douyin", {})
        isolation = set(variants.get("isolation_required", []))

        for field in [
            "cookie_state_profile",
            "historical_feedback",
            "performance_metrics",
            "growth_strategy",
            "platform_source_matrix",
            "tools_capability_analysis",
            "tool_selection_plan",
            "visual_recipe",
            "tool_invocation_manifest",
            "handoff_package",
            "output_dir",
        ]:
            self.assertIn(field, isolation)

        forbidden = " ".join(variants.get("forbidden_cross_account_reuse", []))
        for marker in ["final.mp4", "template", "bgm", "title", "script", "source_material"]:
            self.assertIn(marker, forbidden)


if __name__ == "__main__":
    unittest.main()
