import json

from content_platform.generation_context_compiler import compile_generation_context


def test_juejin_context_excludes_douyin_rules_and_inventory():
    result = compile_generation_context(
        platform="juejin",
        content_format="technical_article",
        stage="generate",
        brief={
            "content_blueprint": {"topic": "Python async", "content_form": "technical_article"},
            "claim_ledger": [{"claim": "async improves throughput", "evidence_path": "docs/evidence.md"}],
            "capability_plan": {"inventory": [{"name": "secret-tool"}], "executed": ["code_examples"]},
            "compiled_skill_rules": {
                "rules": [
                    {"id": "skill:channel-operations-workflow:1", "source": "skill:channel-operations-workflow", "text": "shared rule"},
                    {"id": "skill:juejin-publishing-workflow:1", "source": "skill:juejin-publishing-workflow", "text": "Juejin rule"},
                    {"id": "skill:douyin-daily-analysis-workflow:1", "source": "skill:douyin-daily-analysis-workflow", "text": "Douyin rule"},
                ]
            },
        },
    )
    payload = json.loads(result["text"])
    assert result["char_count"] <= 12000
    assert "Douyin rule" not in result["text"]
    assert "inventory" not in payload
    assert payload["selected_capability"] == ["code_examples"]
    assert payload["claims"][0]["claim"] == "async improves throughput"


def test_retry_context_uses_reduced_budget_and_no_full_inventory():
    result = compile_generation_context(
        platform="wechat",
        content_format="long_article",
        stage="generate",
        retry=True,
        brief={
            "content_blueprint": {"topic": "x" * 5000},
            "claim_ledger": [{"claim": "y" * 5000, "evidence_path": "e"}],
            "capability_plan": {"executed": ["a", "b"], "candidates": ["c"]},
            "compiled_skill_rules": {"rules": [{"id": f"r{i}", "text": "z" * 1000} for i in range(30)]},
        },
    )
    assert result["char_count"] <= 8000
    assert len(result["text"]) == result["char_count"]

