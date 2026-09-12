import hashlib

from content_platform.capability_runtime import execution_evidence_required, execute_generation_capabilities, execute_post_generation_capabilities, validate_generation_execution
from content_platform.execution_dag import execute_capability_dag


def test_automated_generation_rejects_planned_but_unexecuted_capabilities():
    result = validate_generation_execution({"selected": [{"capability_id": "video_toolchain_runner"}], "executed": []}, required=True)
    assert result["passed"] is False
    assert result["failures"] == ["required_capability_not_executed"]


def test_compiled_run_contract_requires_complete_capability_evidence(monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    assert execution_evidence_required({"run_contract": {"version": "run_contract_v2"}}) is True
    assert execution_evidence_required({"automated_workflow": True}) is True
    monkeypatch.delenv("CONTENT_PLATFORM_RUNTIME_MODE")
    assert execution_evidence_required({"run_contract": {"version": "run_contract_v2"}}) is False
    assert execution_evidence_required({}) is False


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


def test_dag_distinguishes_output_artifact_and_effect_verification(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = execute_capability_dag(
        {
            "candidates": [
                {"capability_id": "structure", "stage": "generation"},
                {"capability_id": "voice_engine", "stage": "assets", "verification_level": "artifact_verified"},
                {"capability_id": "media_quality", "stage": "gate", "verification_level": "effect_verified"},
            ]
        },
        {},
        {},
        executor=lambda *_args: {
            "status": "executed",
            "contract_valid": True,
            "output_hash": "sha256:" + "a" * 64,
            "output": {
                "artifact_evidence": [{"path": str(artifact), "sha256": digest}],
                "effect_evidence": {"passed": True, "artifact_sha256": digest, "probe": "quality_probe"},
            },
        },
    )

    assert {row["capability_id"] for row in result["output_verified"]} == {"structure", "voice_engine", "media_quality"}
    assert {row["capability_id"] for row in result["artifact_verified"]} == {"voice_engine", "media_quality"}
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


def test_resumed_capability_uses_current_stricter_verification_policy(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final video")
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    segments = [
        {"scene_id": f"s{index:02d}", "move_id": move, "artifact_verified": True}
        for index, move in enumerate(("push_in", "split_screen", "detail_reveal"), 1)
    ]
    scene_evidence = {
        "passed": True,
        "artifact_sha256": digest,
        "effect_evidence": {"passed": True, "artifact_sha256": digest, "probe": "scene_probe"},
        "scenes": segments,
    }
    prior = {
        "selected": [{
            "capability_id": "shotcraft_moves",
            "stage": "render",
            "required_or_optional": "required",
            "verification_level": "output_verified",
        }],
        "planned": [],
        "executed": [],
        "output_verified": [],
        "artifact_verified": [],
        "effect_verified": [],
        "completed_stages": ["generation"],
        "profile": {"content_format": "long_video"},
    }
    result = execute_post_generation_capabilities(
        prior,
        {"draft_meta": {"scene_execution_evidence": scene_evidence}},
        {"content_blueprint": {"topic": "AI workflow"}, "platform": "youtube"},
        artifacts=[],
        render_manifest={
            "status": "rendered",
            "output": str(final),
            "shotcraft_motion_plan": {"available": True, "shots": segments},
            "segment_motion_evidence": {"segments": segments},
        },
        quality_gate={},
    )

    assert "shotcraft_moves" in {row["capability_id"] for row in result["effect_verified"]}
