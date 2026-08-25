import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from content_platform.adapter_executor import execute_capability
from content_platform.capability_catalog import (
    build_capability_catalog,
    load_capability_registry,
    validate_capability_registry,
)
from content_platform.capability_router import legacy_tool_group_plan, load_registry
from content_platform.execution_dag import execute_capability_dag
from content_platform.tool_selection import (
    build_tools_capability_analysis,
    build_tool_selection_plan,
)


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "creative_capability_registry.json"


def test_registry_has_exact_legacy_group_coverage_and_candidate_appearances():
    registry = load_capability_registry(REGISTRY_PATH)
    groups = registry["groups"]
    appearances = [candidate for group in groups for candidate in group["candidate_ids"]]

    assert len(groups) == 22
    assert len(appearances) == 48
    assert len(set(appearances)) == 47
    assert all(group["candidate_ids"] for group in groups)
    assert all(group["required_policy"] in {"required", "optional"} for group in groups)


def test_catalog_does_not_synthesize_legacy_or_external_entries():
    registry = load_capability_registry(REGISTRY_PATH)
    catalog = build_capability_catalog(registry, legacy_groups={"invented": ["not_in_registry"]})

    assert "not_in_registry" not in {item["id"] for item in catalog["capabilities"]}
    assert catalog["groups"] == registry["groups"]


def test_catalog_rejects_missing_group_reference_and_incomplete_executable():
    registry = load_capability_registry(REGISTRY_PATH)
    broken = copy.deepcopy(registry)
    broken["groups"][0]["candidate_ids"].append("missing_capability")
    broken["capabilities"].append(
        {
            "id": "broken_executable",
            "source": "test",
            "kind": "tool",
            "lifecycle": "executable",
            "stage": "generation",
            "applies_to": ["article"],
            "required_inputs": [],
            "availability_probe": "module:missing",
            "adapter": "python:content_platform.adapters.missing:execute",
            "output_contract": "test_v1",
            "quality_gate": "test_gate",
            "fallback_chain": [],
            "license": "internal",
        }
    )

    result = validate_capability_registry(broken)

    assert result["passed"] is False
    assert "group_orphan_reference:missing_capability" in result["failures"]
    assert any("broken_executable.adapter_not_supported" in item for item in result["failures"])


def test_tool_selection_is_registry_derived_and_fails_required_groups_closed():
    analysis = build_tools_capability_analysis(platform="douyin", content_type="video")
    source = inspect.getsource(__import__("content_platform.tool_selection", fromlist=["x"]))

    assert sum(len(items) for items in analysis["analyzed_tool_groups"].values()) == 36
    assert analysis["selection_status"] == "blocked"
    assert analysis["failures"]
    assert "_default_candidates" not in source
    assert "_fallback_selected_tools" not in source

    plan = build_tool_selection_plan(platform="douyin", content_type="video", capability_analysis=analysis)
    assert plan["selected_tools"] == []
    assert plan["selection_status"] == "blocked"
    assert all("inventory" not in item["reason"].casefold() for item in plan["rejected_tools"])


def test_legacy_group_plan_matches_registry_order():
    registry = load_registry()
    assert legacy_tool_group_plan("video") == {
        group["id"]: group["candidate_ids"]
        for group in registry["groups"]
        if "short_video" in group["applies_to"] or "long_video" in group["applies_to"]
    }


def test_structure_adapter_contract_produces_deterministic_hash():
    capability = next(
        item for item in load_capability_registry(REGISTRY_PATH)["capabilities"]
        if item["id"] == "copywriting_structure_matcher"
    )
    inputs = {"script_text": "结果很好, 但方法和关键步骤是什么?", "segments": ["结果很好", "方法和关键步骤"]}

    first = execute_capability(capability, inputs)
    second = execute_capability(capability, inputs)

    expected = "sha256:" + hashlib.sha256(
        json.dumps(first["output"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert first["status"] == "executed"
    assert first["contract_valid"] is True
    assert first["output_hash"] == expected
    assert second["output_hash"] == first["output_hash"]


def test_broken_bgm_entry_is_inventory_only_and_never_executable():
    capability = next(
        item for item in load_capability_registry(REGISTRY_PATH)["capabilities"]
        if item["id"] == "bgm_fingerprint_gate"
    )

    assert capability["lifecycle"] == "inventory_only"
    result = execute_capability(capability, {"bgm_file_path": "x.mp3", "platform": "douyin"})
    assert result["status"] != "executed"


def test_execution_dag_records_transitions_and_keeps_optional_failure_nonblocking():
    plan = {
        "candidates": [
            {"capability_id": "required_ok", "required_or_optional": "required"},
            {"capability_id": "optional_bad", "required_or_optional": "optional"},
        ],
        "consulted": [{"capability_id": "methodology", "status": "consulted"}],
    }

    def executor(item, _draft, _brief):
        if item["capability_id"] == "required_ok":
            return {"status": "executed", "contract_valid": True, "output_hash": "sha256:ok"}
        return {"status": "failed", "reason": "optional_probe_down", "contract_valid": False}

    result = execute_capability_dag(plan, {}, {}, executor=executor)

    assert [item["capability_id"] for item in result["planned"]] == ["required_ok", "optional_bad"]
    assert [item["capability_id"] for item in result["consulted"]] == ["methodology"]
    assert [item["capability_id"] for item in result["executed"]] == ["required_ok"]
    assert [item["capability_id"] for item in result["artifact_verified"]] == ["required_ok"]
    assert [item["capability_id"] for item in result["optional_failures"]] == ["optional_bad"]
    assert result["passed"] is True
