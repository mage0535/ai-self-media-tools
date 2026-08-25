import hashlib
import inspect
import json
import time
from copy import deepcopy
from pathlib import Path

from content_platform.adapter_executor import execute_capability
from content_platform.adapters import mcp as mcp_adapter
from content_platform.capability_catalog import load_capability_registry
from content_platform.capability_router import load_registry, match_capabilities
from content_platform.capability_runtime import execute_generation_capabilities
from content_platform.execution_dag import execute_capability_dag
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


def test_methodology_unknown_rule_source_fails_contract_and_is_not_consulted():
    capability = next(item for item in load_capability_registry(ROOT / "config" / "creative_capability_registry.json")['capabilities'] if item["id"] == "skill_reference_compiler")

    result = execute_capability(
        capability,
        {
            "platform": "douyin",
            "compiled_skill_rules": {
                "sources": [{"id": "skill:content/shared", "sha256": "sha-source"}],
                "rules": [{"id": "rule-unknown", "source": "skill:content/missing", "text": "Unknown source"}],
            },
        },
    )

    assert result["status"] == "failed"
    assert result["status"] != "consulted"
    assert result["reason"] == "output_contract_invalid"


def _mcp_capability(capability_id="mcp_content_search", namespace="content-search", tool="search"):
    return next(
        item
        for item in load_capability_registry(ROOT / "config" / "creative_capability_registry.json")["capabilities"]
        if item["id"] == capability_id
    )


def test_mcp_registry_declared_tool_is_the_only_allowlist():
    capability = deepcopy(_mcp_capability())
    capability["mcp_tool"] = "registry_only_tool"
    called = []

    def call(namespace, tool, payload, runtime):
        called.append((namespace, tool, payload, runtime))
        return {"items": ["ok"]}

    result = execute_capability(
        capability,
        {
            "mcp_namespace": "content-search",
            "mcp_tool": "registry_only_tool",
            "mcp_input": {"query": "AI workflow"},
            "mcp_caller": call,
            "mcp_runtime": {"request_id": "runtime-1"},
            "affected_output": "trend_evidence",
        },
    )

    assert "CONTENT_MCP_ALLOWLIST" not in inspect.getsource(mcp_adapter)
    assert result["status"] == "executed"
    assert called == [("content-search", "registry_only_tool", {"query": "AI workflow"}, {"request_id": "runtime-1"})]


def test_content_mcp_allowlist_produces_sanitized_hash_evidence():
    capability = _mcp_capability()

    def call(namespace, tool, payload, _runtime):
        assert (namespace, tool) == ("content-search", "search")
        return {"items": [{"id": "result-1", "title": payload["query"]}], "secret": "do-not-leak"}

    inputs = {
        "mcp_namespace": "content-search",
        "mcp_tool": "search",
        "mcp_input": {"query": "AI workflow", "cookie": "private-cookie"},
        "mcp_caller": call,
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
    assert unavailable["output"]["version"] == "mcp_evidence_v1"
    assert unavailable["output"]["status"] == "skipped"
    assert "prior context" not in json.dumps(unavailable["output"])

    def slow_call(*_args):
        time.sleep(0.05)
        return {"items": []}

    timeout = execute_capability(
        capability,
        {
            "mcp_namespace": "memory-context",
            "mcp_tool": "retrieve",
            "mcp_input": {"query": "prior context"},
            "mcp_caller": slow_call,
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
            "mcp_caller": slow_call,
            "mcp_timeout_seconds": 0.001,
            "mcp_fallback": lambda *_args: {"items": [{"id": "fallback-1"}]},
            "affected_output": "memory_context",
        },
    )
    assert fallback["status"] == "fallback"
    assert fallback["status"] != "executed"
    assert fallback["contract_valid"] is False
    assert fallback["output"]["fallback_used"] is True
    assert fallback["output"]["status"] == "fallback"


def test_capability_router_marks_configured_mcp_available_only_with_injected_caller():
    registry = load_registry()
    profile = {"content_format": "article", "platform": "douyin"}
    capability_id = "mcp_content_search"

    unavailable = match_capabilities(profile, registry)
    assert capability_id in {item["capability_id"] for item in unavailable["skipped"]}

    def caller(*_args):
        return {"items": []}

    available = match_capabilities(
        profile,
        registry,
        runtime_context={"mcp_caller": caller, "mcp_runtime": {"request_id": "router-1"}},
    )
    assert capability_id in {item["capability_id"] for item in available["candidates"]}


def test_capability_runtime_injects_mcp_caller_and_runtime_context():
    calls = []

    def caller(namespace, tool, payload, runtime):
        calls.append((namespace, tool, payload, runtime))
        return {"recipe": "verified"}

    runtime = {"request_id": "runtime-2"}
    result = execute_generation_capabilities(
        {"title": "AI workflow", "body": "A short content brief."},
        {
            "content_profile": {"content_format": "article", "platform": "douyin"},
            "platform": "douyin",
            "mcp_caller": caller,
            "mcp_runtime": runtime,
            "mcp_input": {"query": "AI workflow"},
        },
    )

    evidence = [item for item in result["executed"] if item["capability_id"] == "mcp_ai_self_media_content"]
    assert len(evidence) == 1
    assert calls == [("ai-self-media", "build_content_recipe", {"query": "AI workflow"}, runtime)]


def test_fallback_never_becomes_executed_or_artifact_verified_and_required_fails_closed():
    def executor(_item, _draft, _brief):
        return {
            "status": "fallback",
            "output": {"status": "fallback"},
            "contract_valid": False,
            "output_hash": "sha256:fallback",
        }

    required = execute_capability_dag(
        {"candidates": [{"capability_id": "required-mcp", "required_or_optional": "required"}]},
        {},
        {},
        executor=executor,
    )
    optional = execute_capability_dag(
        {"candidates": [{"capability_id": "optional-mcp", "required_or_optional": "optional"}]},
        {},
        {},
        executor=executor,
    )

    assert required["executed"] == []
    assert required["artifact_verified"] == []
    assert required["passed"] is False
    assert optional["executed"] == []
    assert optional["artifact_verified"] == []
    assert optional["passed"] is True
