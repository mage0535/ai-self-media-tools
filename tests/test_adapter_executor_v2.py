from content_platform.adapter_executor import execute_capability


def test_structure_adapter_executes_and_returns_contract():
    result = execute_capability(
        {
            "id": "structure_match",
            "capability_kind": "analyzer",
            "adapter": "python:content_platform.adapters.structure:execute",
            "required_inputs": ["segments"],
            "output_contract": "structure_match_v1",
        },
        {"segments": ["很多人第一步就错了", "真正原因在证据", "按这三步修复"]},
    )
    assert result["status"] == "executed"
    assert result["contract_valid"] is True
    assert result["output_hash"].startswith("sha256:")


def test_executor_rejects_missing_required_input():
    result = execute_capability(
        {"id": "structure_match", "capability_kind": "analyzer", "adapter": "python:content_platform.adapters.structure:execute", "required_inputs": ["segments"]},
        {},
    )
    assert result["status"] == "failed"
    assert "missing_input:segments" in result["reason"]
