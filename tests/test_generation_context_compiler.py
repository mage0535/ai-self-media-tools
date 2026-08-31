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


def test_context_budget_is_measured_in_utf8_bytes_for_chinese_content():
    result = compile_generation_context(
        platform="wechat",
        content_format="long_article",
        stage="generate",
        brief={
            "content_blueprint": {f"section_{index}": "中文内容" * 500 for index in range(12)},
            "claim_ledger": [
                {"claim": "中文事实" * 200, "evidence_path": "证据路径" * 100}
                for _ in range(12)
            ],
            "compiled_skill_rules": {
                "rules": [
                    {"id": f"rule:{index}", "source": "skill:test", "text": "中文规则" * 100}
                    for index in range(30)
                ]
            },
        },
    )

    assert result["byte_count"] == len(result["text"].encode("utf-8"))
    assert result["byte_count"] <= 12000


def test_selected_rules_deduplicate_normalized_text_and_keep_first_provenance():
    result = compile_generation_context(
        platform="wechat",
        content_format="article",
        stage="generate",
        brief={
            "compiled_skill_rules": {
                "rules": [
                    {"id": "project:1", "source": "skill:project", "text": "Keep  a stable rule."},
                    {"id": "hermes:9", "source": "skill:hermes", "text": " keep a stable rule. "},
                    {"id": "project:2", "source": "skill:project", "text": "Use the selected platform format."},
                ]
            }
        },
    )

    rules = json.loads(result["text"])["selected_rule_ids"]
    assert [rule["id"] for rule in rules] == ["project:1", "project:2"]
    assert rules[0]["source"] == "skill:project"
    assert rules[0]["rule_id"] == "project:1"


def test_selected_rules_include_stable_hash_and_hash_changes_when_text_is_tampered():
    brief = {
        "compiled_skill_rules": {
            "rules": [{"id": "project:1", "source": "skill:project", "text": "Keep a stable rule."}]
        }
    }
    original = json.loads(compile_generation_context(
        platform="wechat", content_format="article", stage="generate", brief=brief
    )["text"])["selected_rule_ids"][0]

    brief["compiled_skill_rules"]["rules"][0]["text"] = "Keep a tampered rule."
    tampered = json.loads(compile_generation_context(
        platform="wechat", content_format="article", stage="generate", brief=brief
    )["text"])["selected_rule_ids"][0]

    assert len(original["sha256"]) == 64
    assert original["sha256"] != tampered["sha256"]


def test_generation_context_embeds_auditable_skill_rule_consumption_hash():
    result = compile_generation_context(
        platform="wechat",
        content_format="article",
        stage="generate",
        brief={
            "compiled_skill_rules": {
                "version": "compiled_skill_rules_v1",
                "rules": [{"id": "project:1", "source": "skill:project", "source_hash": "source-sha", "text": "Open with a concrete outcome."}],
            }
        },
    )
    payload = json.loads(result["text"])
    assert payload["skill_rule_consumption"]["consumption_hash"] == result["skill_rule_consumption"]["consumption_hash"]
    assert payload["skill_rule_consumption"]["affected_outputs"] == ["bounded_model_input", "draft"]


def test_consumption_proof_does_not_duplicate_large_rule_id_inventory_into_provider_input():
    rules = [
        {"id": f"skill:large:{index}:" + "x" * 120, "source": "skill:large", "source_hash": "source-sha", "text": f"Rule {index}: " + "detail " * 80}
        for index in range(100)
    ]
    result = compile_generation_context(
        platform="wechat",
        content_format="article",
        stage="generate",
        brief={"compiled_skill_rules": {"version": "compiled_skill_rules_v1", "rules": rules}},
    )
    payload = json.loads(result["text"])
    assert result["byte_count"] <= 12000
    assert payload["skill_rule_consumption"]["rule_count"] == 100
    assert "rule_ids" not in payload["skill_rule_consumption"]
