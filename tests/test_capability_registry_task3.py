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


def test_registry_has_complete_group_coverage_and_valid_candidate_references():
    registry = load_capability_registry(REGISTRY_PATH)
    groups = registry["groups"]
    appearances = [candidate for group in groups for candidate in group["candidate_ids"]]
    capability_ids = {item["id"] for item in registry["capabilities"]}

    assert len(groups) == 22
    assert set(appearances) <= capability_ids
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


def test_registry_mcp_capabilities_exactly_match_content_production_mcp_inventory():
    from content_platform.mcp_server import mcp_tool_inventory

    registry = load_capability_registry(REGISTRY_PATH)
    records = [item for item in registry["capabilities"] if item.get("kind") == "mcp_tool"]
    expected = {
        item["name"]
        for item in mcp_tool_inventory()
        if item["registry_scope"] == "content_production"
    }

    assert {item["mcp_tool"] for item in records} == expected
    assert all(item["mcp_namespace"] == "content-platform" for item in records)
    assert all(item["mcp_scope"] == "content_production" for item in records)
    assert all(item["lifecycle"] == "executable" for item in records)
    assert all(item["availability_probe"] for item in records)
    assert all(item["adapter"] for item in records)
    assert all(item["output_contract"] for item in records)
    assert all(item["quality_gate"] for item in records)


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ({"lifecycle": "inventory_only"}, "mcp_content_search.mcp_inventory_only"),
        ({"mcp_tool": "missing_tool"}, "mcp_content_search.mcp_tool_not_registered:missing_tool"),
        ({"mcp_tool": "publish_job"}, "mcp_content_search.mcp_not_content_production:publish_job"),
    ],
)
def test_registry_rejects_untruthful_mcp_capabilities(mutation, failure):
    registry = load_capability_registry(REGISTRY_PATH)
    broken = copy.deepcopy(registry)
    record = next(item for item in broken["capabilities"] if item["id"] == "mcp_content_search")
    record.update(mutation)

    result = validate_capability_registry(broken)

    assert result["passed"] is False
    assert failure in result["failures"]


def test_registry_rejects_duplicate_mcp_tool_mapping():
    registry = load_capability_registry(REGISTRY_PATH)
    broken = copy.deepcopy(registry)
    record = next(item for item in broken["capabilities"] if item["id"] == "mcp_memory_context")
    record["mcp_tool"] = "content_search"

    result = validate_capability_registry(broken)

    assert result["passed"] is False
    assert "mcp_tool_duplicate:content_search" in result["failures"]


def test_tool_selection_is_registry_derived_and_fails_required_groups_closed():
    analysis = build_tools_capability_analysis(platform="douyin", content_type="video")
    source = inspect.getsource(__import__("content_platform.tool_selection", fromlist=["x"]))

    assert set(analysis["required_tool_groups"]) <= set(analysis["analyzed_tool_groups"])
    assert all(row["status"] == "available" for row in analysis["group_status"].values())
    assert analysis["selection_status"] == "ready"
    assert not analysis["failures"]
    assert "_default_candidates" not in source
    assert "_fallback_selected_tools" not in source

    plan = build_tool_selection_plan(platform="douyin", content_type="video", capability_analysis=analysis)
    assert len(plan["selected_tools"]) >= 6
    assert plan["selection_status"] == "ready"
    assert all("inventory" not in item["reason"].casefold() for item in plan["rejected_tools"])


def test_selection_without_manifest_uses_first_registry_executable_per_group():
    registry = load_capability_registry(REGISTRY_PATH)
    executable = {
        item["id"]
        for item in registry["capabilities"]
        if item.get("lifecycle") == "executable"
    }

    article = build_tool_selection_plan(platform="wechat", content_type="article")
    video = build_tool_selection_plan(platform="douyin", content_type="short_video")

    assert len(article["selected_tools"]) >= 3
    assert len(video["selected_tools"]) >= 6
    assert set(article["selected_tools"]) <= executable
    assert set(video["selected_tools"]) <= executable
    assert all("inventory" not in item["tool"] for item in article["rejected_tools"])
    assert all("inventory" not in item["tool"] for item in video["rejected_tools"])


def test_planned_manifest_accepts_declared_aliases_and_rejects_unknowns():
    plan = build_tool_selection_plan(
        platform="wechat",
        content_type="article",
        planned_manifest={
            "planned_tools": {
                "article_recipe": "legacy workflow alias",
                "preflight_manifest": "legacy workflow alias",
                "unknown_inventory_name": "must not be selected",
            }
        },
    )

    assert plan["selected_tools"] == ["article_recipe", "preflight_manifest"]
    assert [item["tool"] for item in plan["rejected_tools"]] == ["unknown_inventory_name"]
    assert plan["selection_status"] == "ready"


def test_empty_declared_manifest_does_not_fall_back_to_auto_selection():
    plan = build_tool_selection_plan(
        platform="wechat",
        content_type="article",
        planned_manifest={"planned_tools": {}},
    )

    assert plan["selected_tools"] == []
    assert plan["selection_status"] == "empty"


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


def test_runtime_registry_records_are_internal_and_have_evidence_contracts():
    registry = load_capability_registry(REGISTRY_PATH)
    target_ids = {
        "growth_strategy_latest",
        "platform_source_matrix",
        "performance_cycle",
        "duplication_policy",
        "content_platform.content_recipe",
        "seo_geo_check",
        "content_platform.video_recipe",
        "video_toolchain_runner",
        "shotcraft_moves",
        "media_quality",
        "preflight_manifest",
    }

    records = {item["id"]: item for item in registry["capabilities"] if item["id"] in target_ids}
    assert set(records) == target_ids
    assert all(item["lifecycle"] == "executable" for item in records.values())
    assert all(item["license"] == "internal" for item in records.values())
    assert all(item["runtime_evidence"] == "runtime_evidence_v1" for item in records.values())
    assert all(item["adapter"] == "python:content_platform.adapters.runtime:execute" for item in records.values())


def test_runtime_adapter_executes_real_recipe_and_fails_without_evidence():
    registry = load_capability_registry(REGISTRY_PATH)
    capability = next(item for item in registry["capabilities"] if item["id"] == "content_platform.content_recipe")
    inputs = {
        "content_profile": {"content_format": "article", "platform": "wechat"},
        "content_blueprint": {
            "platform": "wechat",
            "content_form": "article",
            "topic": "AI workflow",
            "title": "AI workflow",
            "body": "Problem. Method. Proof. Checklist.",
            "sections": [
                {"id": "problem", "role": "problem"},
                {"id": "method", "role": "method"},
                {"id": "proof", "role": "proof"},
            ],
            "section_image_map": [
                {"section": "problem", "asset_id": "a1"},
                {"section": "method", "asset_id": "a2"},
                {"section": "proof", "asset_id": "a3"},
            ],
        },
    }

    first = execute_capability(capability, inputs)
    second = execute_capability(capability, inputs)
    missing = execute_capability(capability, {"content_profile": inputs["content_profile"], "content_blueprint": {}})

    assert first["status"] == "executed"
    assert first["contract_valid"] is True
    assert first["output"]["version"] == "content_recipe_v1"
    assert first["output_hash"] == second["output_hash"]
    assert missing["status"] == "failed"
    assert "missing_evidence" in missing["reason"]


def test_runtime_adapter_validates_concrete_evidence_without_fabricating_success():
    registry = load_capability_registry(REGISTRY_PATH)
    capability = next(item for item in registry["capabilities"] if item["id"] == "media_quality")
    base = {
        "content_profile": {"content_format": "article", "platform": "wechat"},
        "content_blueprint": {},
        "media_quality_evidence": {"passed": True, "gates": {"article": {"passed": True}}},
    }

    result = execute_capability(capability, base)
    missing = execute_capability(capability, {"content_profile": base["content_profile"], "content_blueprint": {}})

    assert result["status"] == "executed"
    assert result["output"]["version"] == "media_quality_v1"
    assert result["output"]["evidence"]["passed"] is True
    assert missing["status"] == "failed"
    assert "missing_evidence" in missing["reason"]


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


def test_execution_dag_preserves_full_plan_and_defers_future_stages():
    plan = {
        "candidates": [
            {"capability_id": "content_search_adapter", "stage": "collection", "required_or_optional": "required"},
            {"capability_id": "copywriting_structure_matcher", "stage": "generation", "required_or_optional": "required"},
            {"capability_id": "voice_engine", "stage": "assets", "required_or_optional": "required"},
            {"capability_id": "video_toolchain_runner", "stage": "render", "required_or_optional": "required"},
        ]
    }

    result = execute_capability_dag(
        plan,
        {},
        {},
        executor=lambda item, _draft, _brief: {
            "status": "executed",
            "contract_valid": True,
            "output_hash": f"sha256:{item['capability_id']}",
        },
        stages={"collection", "generation"},
    )

    assert [item["capability_id"] for item in result["selected"]] == [
        "content_search_adapter",
        "copywriting_structure_matcher",
        "voice_engine",
        "video_toolchain_runner",
    ]
    assert [item["capability_id"] for item in result["executed"]] == [
        "content_search_adapter",
        "copywriting_structure_matcher",
    ]
    assert [item["capability_id"] for item in result["pending"]] == [
        "voice_engine",
        "video_toolchain_runner",
    ]
    assert all(item["status"] == "pending" for item in result["pending"])
    assert result["passed"] is True


def test_plan_only_runtime_adapter_never_claims_media_execution():
    registry = load_capability_registry(REGISTRY_PATH)
    capability = next(item for item in registry["capabilities"] if item["id"] == "video_toolchain_runner")

    result = execute_capability(
        capability,
        {
            "content_profile": {"content_format": "short_video", "platform": "douyin"},
            "content_blueprint": {
                "video_toolchain_plan": {
                    "required": True,
                    "selected_pipeline": "knowledge_card_video",
                    "template_family": "evidence_cards",
                    "required_tools": ["renderer"],
                }
            },
            "video_toolchain_plan": {
                "required": True,
                "selected_pipeline": "knowledge_card_video",
                "template_family": "evidence_cards",
                "required_tools": ["renderer"],
            },
        },
    )

    assert result["status"] == "planned"
    assert result["contract_valid"] is True
    assert result["status"] != "executed"


def test_router_inherits_requiredness_from_applicable_tool_groups():
    from content_platform.capability_router import match_capabilities

    result = match_capabilities({"platform": "juejin", "content_format": "article"})
    by_id = {item["capability_id"]: item for item in result["candidates"]}

    assert by_id["duplication_policy"]["required_or_optional"] == "required"
    assert by_id["content_platform.content_recipe"]["required_or_optional"] == "required"
    assert by_id["performance_cycle"]["required_or_optional"] == "optional"


def test_render_adapter_only_executes_after_real_renderer_output(tmp_path):
    registry = load_capability_registry(REGISTRY_PATH)
    capability = next(item for item in registry["capabilities"] if item["id"] == "video_toolchain_runner")
    output = tmp_path / "final.mp4"
    output.write_bytes(b"video")

    result = execute_capability(
        capability,
        {
            "content_profile": {"content_format": "short_video"},
            "content_blueprint": {"topic": "AI workflow"},
            "render_manifest": {"ok": True, "status": "rendered", "output": str(output)},
        },
    )

    assert result["status"] == "executed"
    assert result["contract_valid"] is True


def test_every_tool_group_has_an_executable_adapter_candidate():
    registry = load_capability_registry(REGISTRY_PATH)
    by_id = {item["id"]: item for item in registry["capabilities"]}

    missing = [
        group["id"]
        for group in registry["groups"]
        if not any(by_id[candidate]["lifecycle"] == "executable" for candidate in group["candidate_ids"])
    ]

    assert missing == []


def test_delivery_router_selects_exactly_one_policy_compatible_capability():
    from content_platform.capability_router import match_capabilities

    manual = match_capabilities({"platform": "youtube", "content_format": "long_video"})
    automatic = match_capabilities({"platform": "juejin", "content_format": "article"})

    assert "handoff_package_builder" in {item["capability_id"] for item in manual["candidates"]}
    assert "pipeline_publisher" not in {item["capability_id"] for item in manual["candidates"]}
    assert "pipeline_publisher" in {item["capability_id"] for item in automatic["candidates"]}
    assert "handoff_package_builder" not in {item["capability_id"] for item in automatic["candidates"]}


def test_video_layout_formats_route_to_video_capabilities():
    from content_platform.capability_router import match_capabilities

    vertical = match_capabilities({"platform": "kuaishou", "content_format": "vertical_video"})
    horizontal = match_capabilities({"platform": "youtube", "content_format": "horizontal_video"})

    for result in (vertical, horizontal):
        selected = {item["capability_id"] for item in result["candidates"]}
        assert {"content_platform.video_recipe", "video_toolchain_runner", "shotcraft_moves", "voice_engine", "lower_third_subtitle_renderer", "mix_bgm_with_gate", "media_quality"} <= selected


def test_short_post_uses_article_capabilities_without_empty_selection():
    from content_platform.capability_router import match_capabilities

    result = match_capabilities({"platform": "twitter", "content_format": "short_post"})

    assert {"content_platform.content_recipe", "seo_geo_check", "media_quality"} <= {item["capability_id"] for item in result["candidates"]}
