import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.generator import DraftGenerator, ProviderAuthError
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

    def test_article_generator_emits_tool_selection_evidence(self):
        with patch.dict(os.environ, {}, clear=True):
            draft = DraftGenerator({"allow_fallback": True}).generate(
                "AI workflow checklist",
                {"platforms": ["wechat"], "tone": "clear", "audience": "operators"},
            )
        meta = draft["draft_meta"]
        self.assertIn("tools_capability_analysis", meta)
        self.assertIn("tool_selection_plan", meta)
        self.assertIn("image_text_card_recipe", meta)
        self.assertTrue(meta["tools_capability_analysis"]["all_relevant_tool_types_analyzed"])
        self.assertGreaterEqual(len(meta["tool_selection_plan"]["selected_tools"]), 3)
        self.assertEqual(
            set(meta["tool_selection_plan"]["selected_tools"]),
            set(meta["tool_invocation_manifest"]["planned_tools"]),
        )

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
        generator = DraftGenerator({"provider": "hermes-cli", "allow_fallback": False, "hermes_provider": "opencode-go", "hermes_model": "deepseek-v4-flash"})
        with patch("content_platform.generator.subprocess.run", return_value=completed) as run:
            draft = generator.generate("topic", {"audience": "builders"})
        self.assertEqual(draft["provider"], "hermes-cli")
        self.assertTrue(any("Return only JSON" in item for item in run.call_args.args[0]))
        self.assertIn("same-track", next(item for item in run.call_args.args[0] if "Return only JSON" in item))
        self.assertIn("--provider", run.call_args.args[0])
        self.assertIn("opencode-go", run.call_args.args[0])

    def test_generator_classifies_provider_auth_text_instead_of_non_json(self):
        completed = type("Result", (), {"returncode": 0, "stdout": "HTTP 401: Invalid API key.", "stderr": ""})()
        generator = DraftGenerator({"provider": "hermes-cli", "allow_fallback": False, "hermes_provider": "opencode-go", "hermes_model": "deepseek-v4-flash"})
        with patch("content_platform.generator.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(ProviderAuthError, "provider_auth_failed"):
                generator.generate("topic", {"audience": "builders"})

    def test_full_ops_article_generator_marks_missing_platform_evidence_degraded(self):
        with patch.dict(os.environ, {}, clear=True):
            draft = DraftGenerator({"allow_fallback": True}).generate(
                "小红书知识卡片选题",
                {
                    "platforms": ["xiaohongshu"],
                    "tone": "human",
                    "audience": "new creators",
                },
            )
        meta = draft["draft_meta"]
        matrix = meta["platform_source_matrix"]
        self.assertGreaterEqual(len(matrix["attempted_sources"]), 5)
        self.assertEqual(matrix["successful_source_count"], 0)
        self.assertFalse(matrix["platform_internal_verified"])
        self.assertFalse(matrix["current_platform_specific_topic"])
        self.assertTrue(matrix["shared_trend_only"])
        self.assertEqual(meta["strategy_brief"]["platform_source_matrix"], matrix)

    def test_full_ops_article_generator_preserves_real_platform_source_evidence(self):
        source_matrix = {
            "platform": "zhihu",
            "attempted_sources": [
                {"source": "zhihu", "status": "ok", "topic_signal": "AI workflow", "collected_at": "2026-08-16T00:00:00+00:00"},
                {"source": "github", "status": "ok", "topic_signal": "AI workflow", "collected_at": "2026-08-16T00:00:00+00:00"},
            ],
            "platform_internal_verified": True,
            "real_platform_collection_verified": True,
            "trend_evidence": {"source": "zhihu", "collected_at": "2026-08-16T00:00:00+00:00", "samples": [{"title": "AI workflow"}]},
        }
        draft = DraftGenerator({"allow_fallback": True}).generate(
            "AI workflow",
            {"platforms": ["zhihu"], "platform_source_matrix": source_matrix},
        )
        matrix = draft["draft_meta"]["platform_source_matrix"]
        self.assertEqual(matrix["successful_source_count"], 2)
        self.assertTrue(matrix["platform_internal_verified"])
        self.assertTrue(matrix["current_platform_specific_topic"])
        self.assertTrue(matrix["real_platform_collection_verified"])
        self.assertEqual(matrix["trend_evidence"]["source"], "zhihu")

    def test_full_ops_article_generator_does_not_treat_strategy_as_trend_evidence(self):
        source_matrix = {
            "platform": "zhihu",
            "attempted_sources": [
                {"source": "hackernews", "status": "ok"},
                {"source": "zhihu:fresh_growth_strategy", "status": "ok", "evidence_kind": "fresh_account_performance_strategy"},
            ],
            "platform_internal_verified": True,
            "platform_strategy_verified": True,
            "current_platform_specific_topic": False,
            "shared_trend_only": False,
        }
        draft = DraftGenerator({"allow_fallback": True}).generate(
            "AI workflow",
            {"platforms": ["zhihu"], "platform_source_matrix": source_matrix},
        )

        matrix = draft["draft_meta"]["platform_source_matrix"]
        self.assertFalse(matrix["platform_internal_verified"])
        self.assertTrue(matrix["platform_strategy_verified"])
        self.assertFalse(matrix["real_platform_collection_verified"])
        self.assertFalse(matrix["current_platform_specific_topic"])
        self.assertTrue(matrix["shared_trend_only"])

    def test_generator_preserves_auto_topic_signal_alias_in_growth_recipe(self):
        draft = DraftGenerator({"allow_fallback": True}).generate(
            "AI workflow",
            {
                "platforms": ["wechat"],
                "topic_decision": {"score": 1.2, "signals": ["timeliness", "user_benefit"]},
                "platform_source_matrix": {"attempted_sources": [{"source": "wechat", "status": "ok"}]},
            },
        )
        recipe = draft["draft_meta"]["growth_recipe"]
        self.assertEqual(recipe["topic_decision"]["growth_signals"], ["timeliness", "user_benefit"])


if __name__ == "__main__":
    unittest.main()
