from content_platform.capability_runtime import validate_generation_execution


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
