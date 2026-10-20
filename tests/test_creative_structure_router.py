from __future__ import annotations

import pytest


def test_registry_exposes_required_structure_families_and_capabilities():
    from content_platform.creative_structure_router import get_structure_registry

    registry = get_structure_registry()

    assert {
        "document_workflow",
        "screencast",
        "terminal_diff",
        "before_after",
        "diagnostic_console",
        "split_evidence",
        "timeline_process",
    } <= set(registry)
    for profile in registry.values():
        assert set(profile["capabilities"]) == {
            "supported_visual_modes",
            "asset_roles",
            "group_motions",
            "transitions",
            "audio_profiles",
        }
        assert all(profile["capabilities"].values())


@pytest.mark.parametrize(
    ("content_type", "evidence_shapes", "platform", "viewer_job", "expected"),
    [
        ("tutorial", ["document", "annotations"], "wechat", "follow a workflow", "document_workflow"),
        ("tutorial", ["screen_recording"], "bilibili", "reproduce steps", "screencast"),
        ("engineering_change", ["terminal", "code_diff"], "juejin", "review a change", "terminal_diff"),
        ("case_study", ["before", "after"], "douyin", "judge the result", "before_after"),
        ("incident", ["logs", "metrics"], "bilibili", "find root cause", "diagnostic_console"),
        ("analysis", ["claims", "citations"], "wechat", "compare evidence", "split_evidence"),
        ("process", ["milestones", "dates"], "xiaohongshu", "understand progression", "timeline_process"),
        (
            "human_handoff_case",
            ["real_scene", "localized_annotation", "human_decision", "boundary_case"],
            "douyin",
            "understand human handoff",
            "human_handoff_case",
        ),
    ],
)
def test_route_adapts_structure_to_content_evidence_platform_and_viewer_job(
    content_type, evidence_shapes, platform, viewer_job, expected
):
    from content_platform.creative_structure_router import route_creative_structure

    result = route_creative_structure(
        content_type=content_type,
        evidence_shapes=evidence_shapes,
        platform=platform,
        viewer_job=viewer_job,
    )

    assert result["selected"]["family"] == expected
    assert result["selection_basis"] == {
        "content_type": content_type,
        "evidence_shapes": evidence_shapes,
        "platform": platform,
        "viewer_job": viewer_job,
    }
    assert set(result["selected"]["signature"]) == {
        "scene_structure_signature",
        "hook_pattern",
        "copy_structure",
        "layout_family",
        "motion_grammar",
        "transition_grammar",
        "shot_grammar",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_type": "unknown"},
        {"evidence_shapes": ["unknown_shape"]},
        {"platform": "unknown_platform"},
        {"viewer_job": "unknown viewer job"},
    ],
)
def test_unsupported_routing_values_fail_closed(overrides):
    from content_platform.creative_structure_router import UnsupportedRouteValue, route_creative_structure

    request = {
        "content_type": "tutorial",
        "evidence_shapes": ["screen_recording"],
        "platform": "bilibili",
        "viewer_job": "reproduce steps",
    }
    request.update(overrides)

    with pytest.raises(UnsupportedRouteValue):
        route_creative_structure(**request)


def test_recent_structural_repeat_is_rejected_even_when_color_and_theme_change():
    from content_platform.creative_structure_router import (
        RepeatedStructureError,
        fingerprint_structure,
        route_creative_structure,
    )

    request = {
        "content_type": "engineering_change",
        "evidence_shapes": ["terminal", "code_diff"],
        "platform": "juejin",
        "viewer_job": "review a change",
    }
    first = route_creative_structure(**request)["selected"]
    recent = fingerprint_structure({**first, "color_palette": "blue", "theme": "dark"})
    recent["color_palette"] = "orange"
    recent["theme"] = "light"

    with pytest.raises(RepeatedStructureError):
        route_creative_structure(**request, recent_fingerprints=[recent], history_window=1)


def test_three_structural_dimension_changes_count_as_a_distinct_structure():
    from content_platform.creative_structure_router import fingerprint_structure, route_creative_structure

    request = {
        "content_type": "analysis",
        "evidence_shapes": ["claims", "citations"],
        "platform": "wechat",
        "viewer_job": "compare evidence",
    }
    selected = route_creative_structure(**request)["selected"]
    recent = fingerprint_structure(selected)
    for field in ("hook_pattern", "layout_family", "shot_grammar"):
        recent[field] = f"previous-{recent[field]}"

    result = route_creative_structure(**request, recent_fingerprints=[recent])

    assert result["selected"]["family"] == "split_evidence"


def test_repeat_outside_configured_history_window_is_ignored():
    from content_platform.creative_structure_router import fingerprint_structure, route_creative_structure

    request = {
        "content_type": "process",
        "evidence_shapes": ["milestones", "dates"],
        "platform": "xiaohongshu",
        "viewer_job": "understand progression",
    }
    selected = route_creative_structure(**request)["selected"]
    repeated = fingerprint_structure(selected)
    distinct = dict(repeated)
    for field in ("hook_pattern", "layout_family", "shot_grammar"):
        distinct[field] = f"different-{distinct[field]}"

    result = route_creative_structure(
        **request,
        recent_fingerprints=[repeated, distinct],
        history_window=1,
    )

    assert result["selected"]["family"] == "timeline_process"


def test_unverified_external_source_remains_candidate_and_cannot_be_selected():
    from content_platform.creative_structure_router import route_creative_structure

    external = {
        "id": "github-layout-1",
        "origin": "github",
        "url": "https://github.com/example/layout",
        "license": "MIT",
        "source_hash": "sha256:abc123",
        "verified": False,
        "family": "screencast",
    }
    result = route_creative_structure(
        content_type="tutorial",
        evidence_shapes=["screen_recording"],
        platform="bilibili",
        viewer_job="reproduce steps",
        external_candidates=[external],
    )

    assert result["selected"]["source"] == "builtin"
    assert result["external_candidates"] == [
        {**external, "status": "candidate", "selectable": False}
    ]


@pytest.mark.parametrize("missing", ["url", "license", "source_hash"])
def test_external_candidates_without_required_provenance_fail_closed(missing):
    from content_platform.creative_structure_router import InvalidExternalCandidate, route_creative_structure

    external = {
        "id": "web-layout-1",
        "origin": "public_web",
        "url": "https://example.org/layout",
        "license": "CC-BY-4.0",
        "source_hash": "sha256:def456",
        "verified": True,
        "family": "document_workflow",
    }
    del external[missing]

    with pytest.raises(InvalidExternalCandidate):
        route_creative_structure(
            content_type="tutorial",
            evidence_shapes=["document"],
            platform="wechat",
            viewer_job="follow a workflow",
            external_candidates=[external],
        )


@pytest.mark.parametrize("platform", ["tiktok", "youtube", "kuaishou", "shipinhao"])
def test_international_and_short_video_platforms_are_supported(platform):
    from content_platform.creative_structure_router import route_creative_structure

    routed = route_creative_structure(
        content_type="workflow",
        evidence_shapes=["document", "annotations"],
        platform=platform,
        viewer_job="follow a workflow",
    )

    assert routed["selected"]["family"] == "document_workflow"
