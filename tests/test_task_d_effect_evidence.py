from pathlib import Path

from content_platform.adapters import mcp as mcp_adapter
from content_platform.mcp_server import invoke_registered_tool
from content_platform.skill_rule_compiler import (
    compile_rule_consumption,
    compile_skill_rules,
    verify_rule_effect,
)


def _write_skill(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_compiled_rule_identity_is_stable_and_carries_source_and_output_provenance(tmp_path):
    skill = _write_skill(
        tmp_path / "skills" / "content" / "shared" / "SKILL.md",
        "# Hook\n\n- Open with a concrete outcome.\n",
    )
    first = compile_skill_rules([skill], root=tmp_path)
    original = first["rules"][0]

    _write_skill(
        skill,
        "# Unrelated\n\n- State the intended audience.\n\n# Hook\n\n- Open with a concrete outcome.\n",
    )
    second = compile_skill_rules([skill], root=tmp_path)
    retained = next(rule for rule in second["rules"] if rule["text"] == original["text"])

    assert retained["id"] == original["id"]
    assert retained["source_hash"] == second["sources"][0]["sha256"]
    assert retained["affected_outputs"] == ["generation_context", "provider_brief"]


def test_reading_rules_is_consulted_until_matching_downstream_consumption_hash_exists(tmp_path):
    skill = _write_skill(
        tmp_path / "skills" / "content" / "shared" / "SKILL.md",
        "- Open with a concrete outcome.\n",
    )
    compiled = compile_skill_rules([skill], root=tmp_path)
    consumption = compile_rule_consumption(
        compiled,
        selected_rule_ids=[compiled["rules"][0]["id"]],
        affected_outputs=["bounded_model_input", "draft"],
    )

    consulted = verify_rule_effect(consumption, downstream_consumption_hashes=[])
    verified = verify_rule_effect(
        consumption,
        downstream_consumption_hashes=[consumption["consumption_hash"]],
    )

    assert consumption["version"] == "skill_rule_consumption_v1"
    assert consumption["consumption_hash"].startswith("sha256:")
    assert consulted["effect_status"] == "consulted"
    assert consulted["effect_verified"] is False
    assert verified["effect_status"] == "effect_verified"
    assert verified["effect_verified"] is True


def _capability() -> dict:
    return {
        "mcp_namespace": "content-platform",
        "mcp_tool": "memory_context",
    }


def test_mcp_read_is_consulted_and_cannot_verify_effect_without_transport_session_proof():
    inputs = {
        "_capability": _capability(),
        "mcp_namespace": "content-platform",
        "mcp_tool": "memory_context",
        "mcp_input": {"context": "{}"},
        "affected_output": "bounded_model_input",
        "mcp_caller": lambda *_args: {
            "_mcp_transport": "stdio",
            "_mcp_session_id": "claimed-session",
            "result": {"context": {}},
        },
    }

    consulted = mcp_adapter.execute(inputs)
    claimed = mcp_adapter.execute(
        {**inputs, "downstream_consumption_hashes": [consulted["consumption_hash"]]}
    )

    assert consulted["effect_status"] == "consulted"
    assert claimed["effect_status"] == "consulted"
    assert claimed["effect_verified"] is False
    assert claimed["effect_reason"] == "mcp_transport_session_evidence_unverified"


def test_registered_mcp_output_with_matching_downstream_hash_is_effect_verified():
    def caller(namespace, tool, payload, _runtime):
        assert namespace == "content-platform"
        return invoke_registered_tool(tool, payload)

    inputs = {
        "_capability": _capability(),
        "mcp_namespace": "content-platform",
        "mcp_tool": "memory_context",
        "mcp_input": {"context": "{}"},
        "affected_output": "bounded_model_input",
        "mcp_caller": caller,
    }

    consulted = mcp_adapter.execute(inputs)
    verified = mcp_adapter.execute(
        {**inputs, "downstream_consumption_hashes": [consulted["consumption_hash"]]}
    )

    assert consulted["effect_status"] == "consulted"
    assert consulted["transport"] == "in_process_registered_mcp"
    assert consulted["session_id"]
    assert verified["consumption_hash"] == consulted["consumption_hash"]
    assert verified["effect_status"] == "effect_verified"
    assert verified["effect_verified"] is True
