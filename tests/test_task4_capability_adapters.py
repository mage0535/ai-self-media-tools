import hashlib
import json
import time
from pathlib import Path

from content_platform.adapter_executor import execute_capability
from content_platform.capability_catalog import load_capability_registry
from content_platform.skill_rule_compiler import compile_skill_rules, select_platform_rules


ROOT = Path(__file__).resolve().parents[1]


def _skill(path: Path, text: str = "- Apply this content rule.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_skill_compiler_excludes_archive_duplicate_and_unrelated_finance_skills(tmp_path):
    accepted = _skill(tmp_path / "skills" / "content" / "wechat-workflow" / "SKILL.md")
    archive = _skill(tmp_path / "skills" / "content" / "archive" / "SKILL.md")
    hidden_archive = _skill(tmp_path / "skills" / "content" / "_archive" / "SKILL.md")
    duplicate = _skill(tmp_path / "skills" / "content" / "duplicate-workflow" / "SKILL.md")
    trading = _skill(tmp_path / "skills" / "trading" / "SKILL.md")

    compiled = compile_skill_rules([trading, duplicate, hidden_archive, archive, accepted], root=tmp_path)

    assert [source["id"] for source in compiled["sources"]] == ["skill:content/wechat-workflow"]
    assert [rule["source"] for rule in compiled["rules"]] == ["skill:content/wechat-workflow"]


def test_platform_rule_selection_is_deterministic_and_content_relevant():
    rules = [
        {"id": "skill:content/xiaohongshu:1", "source": "skill:content/xiaohongshu", "text": "XHS rule"},
        {"id": "skill:content/shared:2", "source": "skill:content/shared", "text": "Shared rule"},
        {"id": "skill:content/douyin:1", "source": "skill:content/douyin", "text": "Douyin rule"},
        {"id": "skill:content/finance:1", "source": "skill:content/finance", "text": "Finance rule"},
        {"id": "skill:content/shared:1", "source": "skill:content/shared", "text": "Shared rule"},
    ]

    selected = select_platform_rules(rules, "douyin")

    assert [rule["id"] for rule in selected] == [
        "skill:content/douyin:1",
        "skill:content/shared:1",
    ]
    assert select_platform_rules(list(reversed(rules)), "douyin") == selected


def test_methodology_compilation_is_consulted_and_has_reference_evidence():
    capability = next(item for item in load_capability_registry(ROOT / "config" / "creative_capability_registry.json")["capabilities"] if item["id"] == "skill_reference_compiler")
    inputs = {
        "platform": "douyin",
        "compiled_skill_rules": {
            "sources": [{"id": "skill:content/shared", "sha256": "sha-source"}],
            "rules": [{"id": "rule-1", "source": "skill:content/shared", "text": "Use a clear hook."}],
        },
        "affected_outputs": ["generation_context", "provider_brief"],
    }

    result = execute_capability(capability, inputs)

    assert result["status"] == "consulted"
    assert result["status"] != "executed"
    assert result["output"]["rule_ids"] == ["rule-1"]
    assert result["output"]["source_hashes"] == {"skill:content/shared": "sha-source"}
    assert result["output"]["rules_applied"] == ["rule-1"]
    assert result["output"]["affected_outputs"] == ["generation_context", "provider_brief"]
    assert result["output_hash"].startswith("sha256:")


def _mcp_capability(capability_id="mcp_content_search", namespace="content-search", tool="search"):
    return next(
        item
        for item in load_capability_registry(ROOT / "config" / "creative_capability_registry.json")["capabilities"]
        if item["id"] == capability_id
    )


def test_content_mcp_allowlist_produces_sanitized_hash_evidence():
    capability = _mcp_capability()

    def call(namespace, tool, payload):
        assert (namespace, tool) == ("content-search", "search")
        return {"items": [{"id": "result-1", "title": payload["query"]}], "secret": "do-not-leak"}

    inputs = {
        "mcp_namespace": "content-search",
        "mcp_tool": "search",
        "mcp_input": {"query": "AI workflow", "cookie": "private-cookie"},
        "mcp_call": call,
        "affected_output": "trend_evidence",
    }
    first = execute_capability(capability, inputs)
    second = execute_capability(capability, inputs)

    assert first["status"] == "executed"
    evidence = first["output"]
    assert evidence["server_name"] == "content-search"
    assert evidence["tool_name"] == "search"
    assert evidence["status"] == "executed"
    assert evidence["affected_output"] == "trend_evidence"
    assert evidence["input_hash"].startswith("sha256:")
    assert evidence["output_hash"].startswith("sha256:")
    assert "private-cookie" not in json.dumps(evidence)
    assert first["output_hash"] == second["output_hash"]


def test_mcp_rejects_trading_namespace_without_calling_it():
    capability = _mcp_capability(namespace="trading", tool="quote")
    called = []

    result = execute_capability(
        capability,
        {
            "mcp_namespace": "trading",
            "mcp_tool": "quote",
            "mcp_input": {"symbol": "AAPL"},
            "mcp_call": lambda *_args: called.append(True),
            "affected_output": "content_context",
        },
    )

    assert result["status"] == "skipped"
    assert "not_allowlisted" in result["reason"]
    assert called == []


def test_mcp_unavailable_and_timeout_preserve_truthful_fallback_evidence():
    capability = _mcp_capability(capability_id="mcp_memory_context", namespace="memory-context", tool="retrieve")
    unavailable = execute_capability(
        capability,
        {
            "mcp_namespace": "memory-context",
            "mcp_tool": "retrieve",
            "mcp_input": {"query": "prior context"},
            "affected_output": "memory_context",
        },
    )
    assert unavailable["status"] == "skipped"
    assert "unavailable" in unavailable["reason"]

    def slow_call(*_args):
        time.sleep(0.05)
        return {"items": []}

    timeout = execute_capability(
        capability,
        {
            "mcp_namespace": "memory-context",
            "mcp_tool": "retrieve",
            "mcp_input": {"query": "prior context"},
            "mcp_call": slow_call,
            "mcp_timeout_seconds": 0.001,
            "affected_output": "memory_context",
        },
    )
    assert timeout["status"] == "failed"
    assert "timeout" in timeout["reason"]

    fallback = execute_capability(
        capability,
        {
            "mcp_namespace": "memory-context",
            "mcp_tool": "retrieve",
            "mcp_input": {"query": "prior context"},
            "mcp_call": slow_call,
            "mcp_timeout_seconds": 0.001,
            "mcp_fallback": lambda *_args: {"items": [{"id": "fallback-1"}]},
            "affected_output": "memory_context",
        },
    )
    assert fallback["status"] == "executed"
    assert fallback["output"]["fallback_used"] is True
    assert fallback["output"]["status"] == "fallback"
