import pytest

from content_platform.capability_runtime import (
    merge_execution_manifests,
    record_execution_stage,
)


STAGES = ("generation", "assets", "render", "gate", "delivery")


def _hash(index: int) -> str:
    return f"{index:064x}"


def _complete_stage(stage: str, index: int) -> dict:
    node_id = f"{stage}_node"
    return record_execution_stage(
        stage,
        manifest_hash=_hash(index),
        manifest_kind=f"{stage}_manifest",
        planned=[
            {
                "node_id": node_id,
                "selected": True,
                "required": True,
                "artifact_required": True,
            }
        ],
        consulted=[{"node_id": f"{stage}_policy"}],
        executed=[{"node_id": node_id}],
        artifact_verified=[{"node_id": node_id}],
    )


def test_merger_builds_canonical_five_stage_trace_with_manifest_references():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES, 1)]

    trace = merge_execution_manifests(records)

    assert trace["version"] == "execution_trace_v1"
    assert [record["stage"] for record in trace["stages"]] == list(STAGES)
    assert [record["manifest_ref"]["hash"] for record in trace["stages"]] == [
        f"sha256:{_hash(index)}" for index in range(1, 6)
    ]
    assert trace["passed"] is True
    assert trace["failures"] == []
    assert trace["trace_hash"].startswith("sha256:")


def test_recorder_keeps_evidence_states_explicit_and_separate():
    record = record_execution_stage(
        "generation",
        manifest_hash=f"sha256:{_hash(1)}",
        planned=[{"node_id": "writer", "selected": True, "required": True}],
        consulted=[{"node_id": "style_guide"}],
        executed=[{"node_id": "writer"}],
        artifact_verified=[],
    )

    assert record["planned"] == [{"node_id": "writer", "selected": True, "required": True}]
    assert record["consulted"] == [{"node_id": "style_guide"}]
    assert record["executed"] == [{"node_id": "writer"}]
    assert record["artifact_verified"] == []


def test_selected_required_node_without_execution_fails_closed():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES, 1)]
    records[2] = record_execution_stage(
        "render",
        manifest_hash=_hash(3),
        planned=[{"node_id": "renderer", "selected": True, "required": True}],
        executed=[],
        artifact_verified=[],
    )

    trace = merge_execution_manifests(records)

    assert trace["passed"] is False
    assert "required_node_not_executed:render:renderer" in trace["failures"]


def test_required_artifact_verification_is_not_inferred_from_execution():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES, 1)]
    records[4] = record_execution_stage(
        "delivery",
        manifest_hash=_hash(5),
        planned=[
            {
                "node_id": "delivery_receipt",
                "selected": True,
                "required": True,
                "artifact_required": True,
            }
        ],
        executed=[{"node_id": "delivery_receipt"}],
        artifact_verified=[],
    )

    trace = merge_execution_manifests(records)

    assert trace["passed"] is False
    assert "required_artifact_not_verified:delivery:delivery_receipt" in trace["failures"]


def test_optional_or_unselected_nodes_do_not_block_execution_trace():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES, 1)]
    records[1] = record_execution_stage(
        "assets",
        manifest_hash=_hash(2),
        planned=[
            {"node_id": "optional_asset", "selected": True, "required": False},
            {"node_id": "candidate_only", "selected": False, "required": True},
        ],
    )

    trace = merge_execution_manifests(records)

    assert trace["passed"] is True


def test_missing_canonical_stage_fails_closed():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES[:-1], 1)]

    trace = merge_execution_manifests(records)

    assert trace["passed"] is False
    assert "required_stage_missing:delivery" in trace["failures"]


@pytest.mark.parametrize("stage", ["", "publish", "Generation"])
def test_recorder_rejects_noncanonical_stage_names(stage):
    with pytest.raises(ValueError, match="unsupported execution stage"):
        record_execution_stage(stage, manifest_hash=_hash(1))


@pytest.mark.parametrize("manifest_hash", ["", "sha256:short", "not-a-hash"])
def test_recorder_rejects_invalid_manifest_hashes(manifest_hash):
    with pytest.raises(ValueError, match="manifest_hash"):
        record_execution_stage("generation", manifest_hash=manifest_hash)
