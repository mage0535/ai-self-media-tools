import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.generator import DraftGenerator
from content_platform.risk import RiskFilter, redact_secrets


class ContentTests(unittest.TestCase):
    def test_risk_filter_distinguishes_pass_review_and_block(self):
        risk = RiskFilter(block_words=["forbidden"], review_words=["guaranteed"])
        self.assertEqual(risk.evaluate("ordinary copy")["level"], "pass")
        self.assertEqual(risk.evaluate("guaranteed return")["level"], "review")
        self.assertEqual(risk.evaluate("forbidden method")["level"], "block")

    def test_secret_redaction_hides_values(self):
        text = "OPENAI_API_KEY=secret-value token: abcdefghijklmnop"
        redacted = redact_secrets(text)
        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("abcdefghijklmnop", redacted)

    def test_generator_has_deterministic_offline_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            draft = DraftGenerator({"allow_fallback": True}).generate(
                "Local AI workflows",
                {
                    "tone": "clear",
                    "audience": "builders",
                    "reference_posts": [{"title": "Hook", "body": "1. First\n2. Second\nSave this."}],
                },
            )
        self.assertEqual(draft["provider"], "fallback")
        self.assertIn("Local AI workflows", draft["title"])
        self.assertIn("builders", draft["body"])
        self.assertIn("draft_meta", draft)
        self.assertIn("image_prompt", draft["draft_meta"])
        self.assertIn("video_prompt", draft["draft_meta"])
        self.assertTrue(draft["draft_meta"]["style"]["sample_count"] >= 1)
        self.assertIn("viral_score", draft["draft_meta"])
        self.assertIn("content_form", draft["draft_meta"])
        self.assertIn("quality_scores", draft["draft_meta"])
        self.assertIn("rewrite_notes", draft["draft_meta"])

    def test_generator_reads_named_key_from_configured_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "provider.env"
            env_file.write_text("OPENAI_API_KEY=file-key\nUNRELATED=ignored\n", encoding="utf-8")
            generator = DraftGenerator({"env_file": str(env_file), "api_key_env": "OPENAI_API_KEY"})
            with patch.object(generator, "_remote", return_value={"title": "T", "body": "B", "provider": "remote"}) as remote:
                draft = generator.generate("topic")
        self.assertEqual(draft["provider"], "remote")
        self.assertEqual(remote.call_args.args[3], "file-key")

    def test_generator_can_use_hermes_cli_provider(self):
        completed = type("Result", (), {"returncode": 0, "stdout": '{"title":"Remote title","body":"Remote body"}', "stderr": ""})()
        generator = DraftGenerator({"provider": "hermes-cli", "allow_fallback": False})
        with patch("content_platform.generator.subprocess.run", return_value=completed) as run:
            draft = generator.generate("topic", {"audience": "builders"})
        self.assertEqual(draft["provider"], "hermes-cli")
        self.assertTrue(any("Return only JSON" in item for item in run.call_args.args[0]))
        self.assertIn("same-track", run.call_args.args[0][2])


if __name__ == "__main__":
    unittest.main()
