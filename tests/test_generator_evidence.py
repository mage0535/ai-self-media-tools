from content_platform.generator import DraftGenerator
from types import SimpleNamespace


def test_growth_recipe_carries_real_kuaishou_trend_samples_into_the_publish_packet():
    draft_meta = {"strategy": {"primary_platforms": ["kuaishou"]}}
    brief = {
        "platform_source_matrix": {
            "platform": "kuaishou",
            "platform_internal_verified": True,
            "attempted_sources": [
                {"source": "kuaishou_hot", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/1"},
                {"source": "kuaishou_search", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/2"},
                {"source": "kuaishou_creator", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/3"},
            ],
        }
    }

    DraftGenerator._attach_growth_recipe(brief, {}, draft_meta)

    evidence = draft_meta["trend_evidence"]
    assert evidence["source"] == "kuaishou_hot"
    assert evidence["collected_at"]
    assert len(evidence["samples"]) == 3


def test_editorial_generation_prompt_forbids_unverified_anecdotes(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["prompt"] = command[command.index("-z") + 1]
        return SimpleNamespace(returncode=0, stdout='{"title":"标题","body":"正文"}', stderr="")

    monkeypatch.setattr("content_platform.generator.subprocess.run", fake_run)
    generator = DraftGenerator({"hermes_command": "hermes", "allow_fallback": False})
    monkeypatch.setattr(generator, "_normalize", lambda draft, *args: draft)
    brief = {
        "selection_mode": "editorial_calendar",
        "editorial_evidence": {
            "strategy_source": "growth_strategy:test:latest",
            "calendar_column": "engineering",
            "planned_date": "2026-08-18",
            "dedupe": "7d_clear",
        },
        "platform": "juejin",
    }

    generator._hermes("一个工程方法", brief, {"language": "zh", "platform_rules": "", "hook_samples": "", "content_hygiene": {}})

    assert "Do not write first-person operational history" in captured["prompt"]
