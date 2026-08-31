from content_platform.capability_runtime import execute_generation_capabilities, validate_generation_execution
from content_platform.execution_dag import execute_capability_dag


def test_automated_generation_rejects_planned_but_unexecuted_capabilities():
    result = validate_generation_execution({"selected": [{"capability_id": "video_toolchain_runner"}], "executed": []}, required=True)
    assert result["passed"] is False
    assert result["failures"] == ["required_capability_not_executed"]


def test_generation_execution_accepts_artifact_backed_execution():
    result = validate_generation_execution({"selected": [{"capability_id": "structure"}], "executed": [{"capability_id": "structure", "output_hash": "sha256:x"}]}, required=True)
    assert result["passed"] is True


def test_generation_execution_rejects_each_selected_required_capability_that_is_missing():
    result = validate_generation_execution(
        {
            "selected": [
                {"capability_id": "structure", "required_or_optional": "required"},
                {"capability_id": "media", "required_or_optional": "required"},
                {"capability_id": "optional_probe", "required_or_optional": "optional"},
            ],
            "executed": [{"capability_id": "structure", "output_hash": "sha256:x"}],
        },
        required=True,
    )

    assert result["passed"] is False
    assert "required_capability_not_executed:media" in result["failures"]
    assert all("optional_probe" not in failure for failure in result["failures"])


def test_generation_execution_rejects_required_pending_in_a_completed_stage():
    result = validate_generation_execution(
        {
            "selected": [{"capability_id": "video_toolchain_runner", "stage": "render"}],
            "executed": [{"capability_id": "structure", "output_hash": "sha256:x"}],
            "pending": [
                {
                    "capability_id": "video_toolchain_runner",
                    "stage": "render",
                    "required_or_optional": "required",
                    "status": "pending",
                }
            ],
            "completed_stages": ["render"],
        },
        required=True,
    )

    assert result["passed"] is False
    assert "required_capability_pending:render:video_toolchain_runner" in result["failures"]


def test_dag_distinguishes_output_artifact_and_effect_verification():
    result = execute_capability_dag(
        {
            "candidates": [
                {"capability_id": "structure", "stage": "generation"},
                {"capability_id": "voice_engine", "stage": "assets"},
                {"capability_id": "media_quality", "stage": "gate"},
            ]
        },
        {},
        {},
        executor=lambda *_args: {
            "status": "executed",
            "contract_valid": True,
            "output_hash": "sha256:" + "a" * 64,
        },
    )

    assert {row["capability_id"] for row in result["output_verified"]} == {"structure"}
    assert {row["capability_id"] for row in result["artifact_verified"]} == {"voice_engine"}
    assert {row["capability_id"] for row in result["effect_verified"]} == {"media_quality"}
    assert all(row["capability_id"] != "structure" for row in result["artifact_verified"])


def test_generation_runtime_receives_compiled_growth_strategy():
    strategy = {
        "version": "compiled_strategy_v1", "platform": "juejin", "source_sha256": "a" * 64,
        "content_pillars": ["proof"], "structure_pool": ["tutorial", "demo", "postmortem", "checklist", "story"], "hook_templates": [],
        "cta_pool": ["question"], "evidence_policy": {"numeric_claim_requires_source": True},
        "selection_policy": {"shadow_can_create_jobs": False},
    }
    result = execute_generation_capabilities(
        {"title": "AI workflow", "body": "problem method proof with enough content"},
        {"platform": "juejin", "content_form": "article", "strategy": strategy},
    )
    growth = next(row for row in result["executed"] if row["capability_id"] == "growth_strategy_latest")
    assert growth["status"] == "executed"
