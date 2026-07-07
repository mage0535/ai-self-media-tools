import unittest

from content_platform.humanize import naturalize_copy


class HumanizeTests(unittest.TestCase):
    def test_naturalize_copy_returns_scores_and_rewrite_notes(self):
        result = naturalize_copy(
            "In conclusion, this solution is very important. In conclusion, you should use it.",
            {"style": {"opening_patterns": ["Lead with the payoff"], "cta": "Save this"}},
        )
        self.assertIn("body", result)
        self.assertIn("quality_scores", result)
        self.assertIn("quality_gate", result)
        self.assertIn("rewrite_notes", result)
        self.assertGreater(result["quality_scores"]["clarity"], 0)
        self.assertIn("passed", result["quality_gate"])


if __name__ == "__main__":
    unittest.main()
