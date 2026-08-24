from content_platform.execution_dag import execute_capability_dag


def test_required_failure_blocks_and_optional_failure_is_recorded_without_blocking():
    plan = {
        "candidates": [
            {"capability_id": "required", "required_or_optional": "required"},
            {"capability_id": "optional", "required_or_optional": "optional"},
        ],
        "consulted": [{"capability_id": "method", "status": "consulted"}],
    }

    def executor(item, _draft, _brief):
        return {"status": "failed", "reason": item["capability_id"]}

    result = execute_capability_dag(plan, {}, {}, executor=executor)

    assert result["passed"] is False
    assert result["consulted"][0]["status"] == "consulted"
    assert result["failures"][0]["required"] is True
    assert result["optional_failures"][0]["required"] is False


def test_successful_execution_is_distinct_from_selection():
    plan = {"candidates": [{"capability_id": "structure_match", "required_or_optional": "required"}], "consulted": []}
    result = execute_capability_dag(plan, {"body": "show result then steps"}, {}, executor=lambda *_: {"status": "executed", "output_hash": "sha256:x"})
    assert result["passed"] is True
    assert result["executed"][0]["status"] == "executed"
    assert result["selected"][0]["capability_id"] == "structure_match"


def test_optional_failure_does_not_block_stage():
    result = execute_capability_dag(
        {"candidates": [{"capability_id": "optional", "required_or_optional": "optional"}], "consulted": []},
        {},
        {},
        executor=lambda *_: {"status": "failed", "reason": "unavailable"},
    )
    assert result["passed"] is True
    assert result["optional_failures"][0]["capability_id"] == "optional"


def test_execution_result_is_auditable_without_conflating_consulted_and_executed():
    result = execute_capability_dag(
        {"candidates": [], "consulted": [{"capability_id": "method"}], "skipped": []},
        {},
        {},
        executor=lambda *_: {"status": "executed", "output_hash": "sha256:x"},
    )
    assert result["version"] == "capability_execution_dag_v1"
    assert result["consulted"][0]["status"] == "consulted"
    assert result["executed"] == []
    assert result["failures"] == []
