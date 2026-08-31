import pytest

from content_platform.capability_runtime import (
    merge_execution_manifests,
    record_execution_stage,
)
from content_platform.execution_trace import build_pre_delivery_trace, complete_delivery_trace


STAGES = ("collection", "selection", "blueprint", "generation", "assets", "render", "gate", "delivery")


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
        f"sha256:{_hash(index)}" for index in range(1, len(STAGES) + 1)
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
    records[5] = record_execution_stage(
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
    records[7] = record_execution_stage(
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
    records[4] = record_execution_stage(
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


def test_pre_delivery_trace_is_pending_not_failed_when_real_prior_stages_pass():
    trace = build_pre_delivery_trace(
        capability_execution={
            "selected": [{"capability_id": "copywriting_structure_matcher", "stage": "generation", "required_or_optional": "required"}],
            "consulted": [{"capability_id": "guide"}],
            "executed": [{"capability_id": "copywriting_structure_matcher", "stage": "generation", "output_hash": "sha256:x"}],
        },
        artifacts=[{"kind": "image", "path": "image.png", "checksum": "abc", "capability_id": "voice_engine"}],
        assets_required=True,
        render_manifest={},
        render_required=False,
        quality_gate={"passed": True, "score": 5},
    )
    assert trace["passed"] is None
    assert trace["status"] == "pending_delivery"
    assert [row["stage"] for row in trace["stages"]] == list(STAGES[:-1])


def test_capability_dag_execution_records_retain_selected_stage():
    from content_platform.execution_dag import execute_capability_dag

    plan = {
        "candidates": [
            {"capability_id": "source", "stage": "collection", "required_or_optional": "required"},
            {"capability_id": "dedup", "stage": "selection", "required_or_optional": "required"},
        ]
    }

    result = execute_capability_dag(
        plan, {}, {},
        stages={"collection", "selection"},
        executor=lambda item, draft, brief: {"status": "executed", "contract_valid": True, "output_hash": "sha256:" + "a" * 64},
    )

    assert {(row["capability_id"], row["stage"]) for row in result["executed"]} == {("source", "collection"), ("dedup", "selection")}
    assert {(row["capability_id"], row["stage"]) for row in result["output_verified"]} == {("source", "collection"), ("dedup", "selection")}


def test_delivery_completion_makes_canonical_trace_pass():
    pending = build_pre_delivery_trace(
        capability_execution={
            "selected": [{"capability_id": "copywriting_structure_matcher", "stage": "generation", "required_or_optional": "required"}],
            "executed": [{"capability_id": "copywriting_structure_matcher", "stage": "generation", "output_hash": "sha256:x"}],
        },
        artifacts=[],
        assets_required=False,
        render_manifest={},
        render_required=False,
        quality_gate={"passed": True},
    )
    trace = complete_delivery_trace(
        pending,
        platform="xiaohongshu",
        result={"ok": True, "status": "handoff_pending", "external_id": "handoff.json"},
    )
    assert trace["passed"] is True
    assert trace["status"] == "completed"


def test_multiple_platform_deliveries_share_one_delivery_stage():
    pending = build_pre_delivery_trace(
        capability_execution={"selected": [], "executed": []}, artifacts=[], assets_required=False,
        render_manifest={}, render_required=False, quality_gate={"passed": True},
    )
    first = complete_delivery_trace(pending, platform="wechat", result={"ok": True, "status": "drafted", "external_id": "draft-1"})
    second = complete_delivery_trace(first, platform="zhihu", result={"ok": True, "status": "drafted", "external_id": "draft-2"})
    assert [row["stage"] for row in second["stages"]].count("delivery") == 1
    delivery = next(row for row in second["stages"] if row["stage"] == "delivery")
    assert {row["node_id"] for row in delivery["executed"]} == {"pipeline_publisher"}


def test_dry_run_delivery_uses_verified_boundary_without_claiming_publish():
    pending = build_pre_delivery_trace(
        capability_execution={"selected": [], "executed": []}, artifacts=[], assets_required=False,
        render_manifest={}, render_required=False, quality_gate={"passed": True},
    )

    trace = complete_delivery_trace(
        pending,
        platform="kuaishou",
        result={"ok": True, "status": "dry_run", "external_id": "outbox/kuaishou.json"},
    )

    delivery = next(row for row in trace["stages"] if row["stage"] == "delivery")
    assert trace["passed"] is True
    assert {row["node_id"] for row in delivery["executed"]} == {"delivery_boundary_probe"}
    assert {row["node_id"] for row in delivery["artifact_verified"]} == {"delivery_boundary_probe"}
    assert "pipeline_publisher" not in str(delivery)


def test_full_selected_plan_maps_to_registry_ids_and_terminal_evidence():
    selected = [
        {"capability_id": "platform_source_matrix", "stage": "collection", "required_or_optional": "required"},
        {"capability_id": "duplication_policy", "stage": "selection", "required_or_optional": "required"},
        {"capability_id": "growth_strategy_latest", "stage": "blueprint", "required_or_optional": "required"},
        {"capability_id": "copywriting_structure_matcher", "stage": "generation", "required_or_optional": "required"},
        {"capability_id": "voice_engine", "stage": "assets", "required_or_optional": "required", "artifact_required": True},
        {"capability_id": "video_toolchain_runner", "stage": "render", "required_or_optional": "required", "artifact_required": True},
        {"capability_id": "media_quality", "stage": "gate", "required_or_optional": "required", "artifact_required": True},
    ]
    early = selected[:4]
    pending = [{**item, "status": "pending"} for item in selected[4:]]
    trace = build_pre_delivery_trace(
        capability_execution={"selected": selected, "executed": early, "pending": pending},
        artifacts=[{"capability_id": "voice_engine", "path": "voice.wav", "checksum": "abc"}],
        assets_required=True,
        render_manifest={
            "ok": True,
            "status": "rendered",
            "capability_evidence": [
                {"capability_id": "video_toolchain_runner", "status": "executed", "artifact_verified": True}
            ],
        },
        render_required=True,
        quality_gate={
            "passed": True,
            "capability_evidence": [
                {"capability_id": "media_quality", "status": "executed", "artifact_verified": True}
            ],
        },
    )
    trace = complete_delivery_trace(
        trace,
        platform="douyin",
        result={"ok": True, "status": "published", "external_id": "post-1"},
    )

    assert trace["passed"] is True
    planned_ids = {
        item["node_id"]
        for stage in trace["stages"]
        for item in stage["planned"]
    }
    assert set(item["capability_id"] for item in selected) <= planned_ids
    assert "pipeline_publisher" in planned_ids
    assert not planned_ids.intersection({"media_assets", "media_render", "final_quality_gate"})


def test_deferred_required_capability_cannot_escape_terminal_validation():
    trace = build_pre_delivery_trace(
        capability_execution={
            "selected": [
                {"capability_id": "video_toolchain_runner", "stage": "render", "required_or_optional": "required", "artifact_required": True}
            ],
            "pending": [
                {"capability_id": "video_toolchain_runner", "stage": "render", "required_or_optional": "required", "status": "pending"}
            ],
        },
        artifacts=[],
        assets_required=False,
        render_manifest={"ok": True, "status": "rendered"},
        render_required=True,
        quality_gate={"passed": True},
    )

    assert trace["passed"] is False
    assert "required_node_not_executed:render:video_toolchain_runner" in trace["failures"]
    assert "required_artifact_not_verified:render:video_toolchain_runner" in trace["failures"]


def test_generic_placeholder_only_trace_fails_validation():
    records = [_complete_stage(stage, index) for index, stage in enumerate(STAGES, 1)]
    records[4] = record_execution_stage(
        "assets",
        manifest_hash=_hash(5),
        planned=[{"node_id": "media_assets", "selected": True, "required": True}],
        executed=[{"node_id": "media_assets"}],
    )

    trace = merge_execution_manifests(records)

    assert trace["passed"] is False
    assert "generic_placeholder_node_forbidden:assets:media_assets" in trace["failures"]
