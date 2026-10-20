from __future__ import annotations

from pathlib import Path

import pytest

from content_platform.video_generation_contract import (
    InvalidGenerationContract,
    compile_generation_contract,
)
from content_platform.video_toolchain import build_video_toolchain_plan


PLATFORMS = (
    "bilibili",
    "youtube_long_form",
    "youtube_shorts",
    "douyin_ai",
    "kuaishou",
    "shipinhao",
    "tiktok",
)


def _audio_plan() -> dict:
    return {
        "route": "embedded_licensed_bgm",
        "route_reason": "licensed instrumental bed supports narration",
        "source_audio_action": "replace",
        "fallback_route": "sfx_only",
        "license": "Pixabay Content License",
        "source_url": "https://pixabay.com/music/auditable-test-bed",
        "fingerprint": "sha256:auditable-test-bed",
        "rights_scope": "worldwide_social_video",
    }


def _strategy(platform: str) -> dict:
    return {
        "primary_platforms": [platform],
        "content_form": "knowledge_card_video",
        "asset_plan": ["knowledge_cards", "human_voiceover"],
        "audio_plan": _audio_plan(),
    }


@pytest.mark.parametrize("platform", PLATFORMS)
def test_generated_plan_has_generation_contract_structure_without_inventing_hot_samples(
    platform: str, tmp_path: Path
) -> None:
    brief = {
        "topic": "Auditable invoice workflow",
        "lane": "real_world_ai_implementation",
        "content_type": "workflow",
        "evidence_shapes": ["document", "annotations"],
        "viewer_job": "follow a workflow",
    }

    first = build_video_toolchain_plan(_strategy(platform), brief)
    second = build_video_toolchain_plan(_strategy(platform), brief)

    assert first["run_id"] == second["run_id"]
    assert first["run_id"].startswith(f"video-{platform}-")
    assert first["revision"] == 1
    assert first["attempt_id"] == "attempt-1"
    assert first["lane"] == brief["lane"]
    assert first["content_type"] == brief["content_type"]
    assert first["evidence_shapes"] == brief["evidence_shapes"]
    assert first["viewer_job"] == brief["viewer_job"]
    assert first["hot_viral_samples"] == []
    assert first["hot_viral_source_statuses"] == {}
    assert first["canonical_output_name"] == "final.mp4"
    assert len(first["visual_contract"]) == 8

    plan_path = tmp_path / f"{platform}.json"
    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidGenerationContract, match="hot_viral_samples"):
        compile_generation_contract(first, output_dir=tmp_path, input_paths={"plan": plan_path})


@pytest.mark.parametrize("platform", PLATFORMS)
def test_minimal_production_plan_is_complete_except_for_unavailable_hot_samples(
    platform: str, tmp_path: Path
) -> None:
    plan = build_video_toolchain_plan(
        _strategy(platform),
        {"topic": "Minimal production topic"},
    )

    for field in (
        "run_id",
        "revision",
        "attempt_id",
        "lane",
        "content_type",
        "evidence_shapes",
        "viewer_job",
        "canonical_output_name",
        "visual_contract",
    ):
        assert plan[field] not in (None, "", [], {})
    assert plan["hot_viral_samples"] == []
    assert plan["hot_viral_source_statuses"] == {}

    plan_path = tmp_path / f"minimal-{platform}.json"
    plan_path.write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidGenerationContract, match="hot_viral_samples"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def _native_sample(platform: str, source: str) -> dict:
    return {
        "platform": platform,
        "lane": "real_world_ai_implementation",
        "source": source,
        "signal_type": "ranked_content_candidate",
        "canonical_url": f"https://example.com/{platform}/real-work-1",
        "content_id": "real-work-1",
        "author": "observed-creator",
        "published_at": "2026-09-16T08:00:00+00:00",
        "observed_at": "2026-09-16T09:00:00+00:00",
        "metrics": {"views": 120000, "likes": 8000},
        "content_evidence": {"frames": ["observed-frame-1"], "transcript": "observed"},
        "breakdown": {
            "copy": "result first",
            "hook": "show the result",
            "writing_style": "direct",
            "illustration": "annotated documents",
            "cover": "input to result",
            "video_structure": "problem-steps-result",
            "motion": "field reveal",
            "transition": "match cuts",
            "CTA": "review the workflow",
        },
    }


@pytest.mark.parametrize("platform", PLATFORMS)
def test_real_hot_samples_are_propagated_from_existing_brief_and_compile(
    platform: str, tmp_path: Path
) -> None:
    source = f"{platform}_observed_public_work"
    sample = _native_sample(platform, source)
    strategy = {
        **_strategy(platform),
        "hot_viral_samples": [],
        "hot_viral_source_statuses": {},
    }
    plan = build_video_toolchain_plan(
        strategy,
        {
            "topic": "Auditable invoice workflow",
            "lane": "real_world_ai_implementation",
            "content_type": "workflow",
            "evidence_shapes": ["document", "annotations"],
            "viewer_job": "follow a workflow",
            "hot_viral_samples": [sample],
            "hot_viral_source_statuses": {source: "ready"},
        },
    )

    assert plan["hot_viral_samples"] == [sample]
    assert plan["hot_viral_samples"][0] is not sample
    assert plan["hot_viral_source_statuses"] == {source: "ready"}

    plan_path = tmp_path / f"ready-{platform}.json"
    plan_path.write_text("{}", encoding="utf-8")
    contract = compile_generation_contract(
        plan, output_dir=tmp_path, input_paths={"plan": plan_path}
    )
    assert contract["hot_viral_intelligence"]["status"] == "native_ready"
    assert contract["run_manifest"].spec.run_id == plan["run_id"]


def test_generated_run_id_changes_when_contract_driving_context_changes() -> None:
    strategy = _strategy("tiktok")
    base = {
        "topic": "Auditable invoice workflow",
        "lane": "real_world_ai_implementation",
        "content_type": "workflow",
        "evidence_shapes": ["document", "annotations"],
        "viewer_job": "follow a workflow",
    }

    first = build_video_toolchain_plan(strategy, base)
    changed = build_video_toolchain_plan(
        strategy,
        {**base, "viewer_job": "review a change"},
    )

    assert first["run_id"] != changed["run_id"]
    assert first["run_id_basis_sha256"] != changed["run_id_basis_sha256"]
