from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _breakdown() -> dict:
    return {
        "copy": "result first",
        "hook": "show duplicate invoice",
        "writing_style": "direct professional",
        "illustration": "annotated documents",
        "cover": "three inputs to three states",
        "video_structure": "conflict-input-extract-match-review",
        "motion": "local field reveal",
        "transition": "semantic match cuts",
        "CTA": "which exception first",
    }


def _native_sample() -> dict:
    return {
        "platform": "tiktok",
        "lane": "real_world_ai_implementation",
        "source": "tiktok_public_work",
        "signal_type": "ranked_content_candidate",
        "canonical_url": "https://www.tiktok.com/@creator/video/123",
        "content_id": "123",
        "author": "creator",
        "published_at": "2026-09-16T08:00:00+00:00",
        "observed_at": "2026-09-16T09:00:00+00:00",
        "metrics": {"views": 120000, "likes": 8000},
        "content_evidence": {"frames": ["frame-1"], "transcript": "evidence"},
        "breakdown": _breakdown(),
    }


def _generation_quality_contract() -> dict:
    return {
        "audience": "finance operations staff",
        "repeated_task": "review duplicate invoices before payment",
        "ai_intervention": "extract and match invoice fields",
        "verifiable_result": "a review queue with matched and conflicting fields",
        "human_handoff": "a finance reviewer approves or rejects every flagged payment",
        "viewer_promise": "understand how an exception becomes a review task and where AI must stop",
        "hook": {
            "scene": "two invoices request payment for the same order",
            "conflict": "their totals match but the invoice identities do not",
            "consequence": "an unchecked duplicate can be paid twice",
            "watch_reason": "the workflow reveals the conflicting fields before payment",
        },
        "evidence_ledger": [
            {"claim": "duplicate fields enter review", "status": "measured", "source": "invoice review log"}
        ],
        "beats": [
            {
                "beat_id": f"s{index:02d}",
                "content_job": f"workflow step {index}",
                "claim": f"claim {index}",
                "evidence": f"evidence {index}",
                "viewer_result": f"decision {index}",
            }
            for index in range(1, 9)
        ],
        "failure_boundary": {
            "trigger": "missing purchase order or unreadable field",
            "failure_mode": "a false match or unresolved exception",
            "verification_action": "finance checks the source documents",
            "authority_limit": "AI cannot approve payment",
        },
        "cta": {
            "audience_identity": "invoice reviewers",
            "specific_question": "Which exception consumes the most review time?",
            "next_value": "the next workflow will break down the highest-frequency exception",
        },
    }


def _plan() -> dict:
    return {
        "run_id": "tiktok-invoice-001",
        "revision": 1,
        "platforms": ["tiktok"],
        "lane": "real_world_ai_implementation",
        "content_type": "workflow",
        "evidence_shapes": ["document", "annotations"],
        "viewer_job": "follow a workflow",
        "canonical_output_name": "final.mp4",
        "audio_plan": {
            "route": "embedded_licensed_bgm",
            "route_reason": "licensed bed supports the narrated workflow",
            "source_audio_action": "replace",
            "fallback_route": "sfx_only",
            "license": "Pixabay Content License",
            "source_url": "https://pixabay.com/music/workflow-bed",
            "fingerprint": "sha256:workflow-bed",
            "rights_scope": "worldwide_social_video",
        },
        "generation_quality_contract": _generation_quality_contract(),
        "hot_viral_samples": [_native_sample()],
        "hot_viral_source_statuses": {"tiktok_public_work": "ready"},
        "visual_contract": [
            {
                "beat_id": f"s{index:02d}",
                "content_job": f"workflow step {index}",
                "visual_hook": f"show evidence change {index}",
                "visual_mode": "annotation_callout",
                "template_id": f"annotation_callout_{index}",
                "evidence_asset": f"evidence-{index}.png",
                "group_motion": ["callout_draw"],
                "platform_reason": "TikTok workflow evidence",
                "reading_hold_seconds": 2.0,
            }
            for index in range(1, 9)
        ],
    }


def test_compile_generation_contract_binds_strategy_structure_and_canonical_output(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import compile_generation_contract

    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    contract = compile_generation_contract(_plan(), output_dir=tmp_path, input_paths={"plan": plan_path})

    assert contract["hot_viral_intelligence"]["status"] == "native_ready"
    assert contract["creative_structure"]["selected"]["family"] == "document_workflow"
    assert contract["generation_quality"]["passed"] is True
    assert contract["generation_quality"]["contract"]["human_handoff"].startswith("a finance reviewer")
    assert contract["platform_profile"]["id"] == "tiktok"
    assert contract["platform_profile"]["beat_count_range"] == [8, 8]
    assert contract["canonical_output"] == str((tmp_path / "final.mp4").resolve())
    assert contract["run_manifest"].missing_outputs == ("video", "cover")
    assert contract["run_manifest"].spec.run_id == "tiktok-invoice-001"


@pytest.mark.parametrize("platform", ["douyin", "youtube"])
def test_compile_generation_contract_rejects_ambiguous_platform_before_rendering(
    tmp_path: Path, platform: str
) -> None:
    from content_platform.video_generation_contract import (
        InvalidGenerationContract,
        compile_generation_contract,
    )

    plan = _plan()
    plan["platforms"] = [platform]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidGenerationContract, match="ambiguous"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_compile_generation_contract_applies_platform_beat_count(tmp_path: Path) -> None:
    from content_platform.generation_quality_contract import InvalidGenerationQualityContract
    from content_platform.video_generation_contract import compile_generation_contract

    plan = _plan()
    plan["generation_quality_contract"]["beats"].pop()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidGenerationQualityContract, match="profile requires 8..8 beats"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_compile_generation_contract_derives_attempt_identity_from_plan(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import compile_generation_contract

    plan = _plan()
    plan["attempt"] = 24
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    contract = compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})

    assert contract["run_manifest"].spec.attempt_id == "attempt-24"
    assert contract["run_manifest"].to_dict()["attempt_id"] == "attempt-24"


def test_compile_generation_contract_rejects_conflicting_attempt_identity(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan.update({"attempt": 24, "attempt_id": "attempt-23"})
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidGenerationContract, match="attempt identity conflict"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


@pytest.mark.parametrize(
    "missing",
    [
        "platforms",
        "lane",
        "content_type",
        "evidence_shapes",
        "viewer_job",
        "hot_viral_samples",
        "visual_contract",
        "audio_plan",
    ],
)
def test_compile_generation_contract_fails_closed_when_required_context_is_missing(tmp_path: Path, missing: str) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan.pop(missing)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidGenerationContract, match=missing):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_canonical_output_must_be_a_plain_mp4_filename(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    for invalid in ("*.mp4", "nested/final.mp4", "final.mov", ""):
        plan = _plan()
        plan["canonical_output_name"] = invalid
        with pytest.raises(InvalidGenerationContract, match="canonical_output_name"):
            compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_generation_contract_carries_validated_audio_plan(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import compile_generation_contract

    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    contract = compile_generation_contract(_plan(), output_dir=tmp_path, input_paths={"plan": plan_path})

    assert contract["audio_plan"]["route"] == "embedded_licensed_bgm"
    assert contract["audio_plan"]["fingerprint"] == "sha256:workflow-bed"


def test_original_workflow_video_rejects_sfx_only_audio_route(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan["audio_plan"] = {
        "route": "sfx_only",
        "route_reason": "avoid licensing work",
        "source_audio_action": "replace",
        "fallback_route": None,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(
        InvalidGenerationContract,
        match="sfx_only|no_bgm_approved|approval_source",
    ):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_generation_contract_rejects_incomplete_audio_route(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan["audio_plan"] = {
        "route": "preserve_source_audio",
        "route_reason": "retain licensed source performance",
        "source_audio_action": "preserve",
        "fallback_route": None,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidGenerationContract, match="source_audio_rights"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={"plan": plan_path})


def test_runner_strict_dry_run_persists_generation_contract_and_trusted_manifest(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "out"
    plan = _plan()
    plan.update(
        {
            "strict_generation_contract": True,
            "selected_pipeline": "knowledge_card_video",
            "template_family": "knowledge_card_motion_case",
        }
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    script = "\n\n".join(f"Distinct workflow beat {index} with concrete evidence." for index in range(1, 9))
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "video_toolchain_runner.py"), script, "Invoice matching"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "VIDEO_OUTPUT_DIR": str(output_dir),
            "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            "VIDEO_TOOLCHAIN_DRY_RUN": "1",
        },
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    generation = json.loads((output_dir / "video_generation_contract.json").read_text(encoding="utf-8"))
    trusted = json.loads((output_dir / "trusted_run_manifest.json").read_text(encoding="utf-8"))
    runner = json.loads((output_dir / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
    scenes = json.loads((output_dir / "scene_contract.json").read_text(encoding="utf-8"))["scenes"]
    assert generation["hot_viral_intelligence"]["status"] == "native_ready"
    assert generation["creative_structure"]["selected"]["family"] == "document_workflow"
    assert trusted["state"] == "CONTRACT_VALIDATED"
    assert {row["name"]: row["role"] for row in trusted["artifacts"]} == {
        "plan": "INPUT",
        "script": "INPUT",
        "video": "OUTPUT",
        "cover": "OUTPUT",
    }
    assert runner["video_generation_contract"]["canonical_output"].endswith("/final.mp4")
    # Explicit topic-authored modes are authoritative; the generic structure
    # router must not silently replace them with its default sequence.
    assert [scene["visual_mode"] for scene in scenes] == [
        "annotation_callout",
    ] * 8
    assert [scene["content_job"] for scene in scenes] == [
        f"workflow step {index}" for index in range(1, 9)
    ]


def test_runner_uses_contract_canonical_cover_path_for_generated_cover(tmp_path: Path) -> None:
    from scripts.video_toolchain_runner import _cover_output_path

    canonical = tmp_path / "release-cover.png"

    assert _cover_output_path(
        tmp_path,
        orientation="vertical",
        generation_contract={"canonical_cover": str(canonical)},
    ) == canonical.resolve()
    assert _cover_output_path(
        tmp_path,
        orientation="horizontal",
        generation_contract=None,
    ) == tmp_path / "cover_1920x1080.jpg"


def test_runner_writes_sha_bound_evidence_for_generated_cover(tmp_path: Path) -> None:
    import hashlib
    import json

    from scripts.video_toolchain_runner import _write_generated_cover_evidence

    cover = tmp_path / "cover.png"
    cover.write_bytes(b"independent-cover")
    evidence_path = tmp_path / "cover_evidence.json"

    payload = _write_generated_cover_evidence(
        cover_path=cover,
        evidence_path=evidence_path,
        platform="kuaishou",
        title="设备还没坏，AI为什么先叫你检修？",
        subtitle="电机仍在转，但异常趋势已经出现",
    )

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == payload
    assert payload["cover_sha256"] == hashlib.sha256(cover.read_bytes()).hexdigest()
    assert payload["layout_key"] == "hero_conflict"
    assert payload["title"] == "设备还没坏，AI为什么先叫你检修？"
    assert payload["hook"]
    assert payload["conflict_or_payoff"]
    assert payload["content_match_reason"]
    assert payload["focal_subjects"]
    assert payload["degraded"] is False


def test_runner_release_bridge_calls_runtime_and_marks_handoff_ready(tmp_path: Path) -> None:
    from content_platform.video_run import RunState
    from scripts.video_toolchain_runner import _release_generation_candidate

    candidate = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    cover_evidence = tmp_path / "cover_evidence.json"
    candidate.write_bytes(b"video")
    cover.write_bytes(b"cover")
    cover_evidence.write_text("{}", encoding="utf-8")
    generation_contract = {
        "run_manifest": SimpleNamespace(state=RunState.ASSETS_VALIDATED),
        "canonical_cover": str(cover),
    }
    runner_manifest = {"status": "rendered_unverified"}
    released = SimpleNamespace(state=RunState.HANDOFF_READY)

    with patch(
        "content_platform.video_release_runtime.release_rendered_candidate",
        return_value=released,
    ) as release:
        result = _release_generation_candidate(
            generation_contract,
            output_dir=tmp_path,
            candidate=candidate,
            plan={"platforms": ["bilibili"], "cover_evidence_path": str(cover_evidence)},
            runner_manifest=runner_manifest,
        )

    assert result is released
    release.assert_called_once()
    assert release.call_args.kwargs["manifest"].state is RunState.ASSETS_VALIDATED
    assert release.call_args.kwargs["candidate"] == candidate
    assert release.call_args.kwargs["cover"] == cover
    assert runner_manifest["status"] == "handoff_ready"


def test_generation_contract_blocks_degraded_hot_evidence_without_strategy_context(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan["platforms"] = ["tiktok"]
    plan["allow_degraded_hot_intelligence"] = True
    plan["allow_degraded_render"] = True
    plan["degraded_source"] = True
    plan["degradation_reason"] = "target platform native metrics unavailable; adjacent public signals only"
    plan["research_source_count"] = 5
    plan["hot_viral_samples"] = [{}]
    with pytest.raises(InvalidGenerationContract, match="hot_viral_samples blocked"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={})


def test_generation_contract_blocks_undeclared_hot_evidence_degradation(tmp_path: Path) -> None:
    from content_platform.video_generation_contract import InvalidGenerationContract, compile_generation_contract

    plan = _plan()
    plan["platforms"] = ["tiktok"]
    plan["hot_viral_samples"] = [{}]
    with pytest.raises(InvalidGenerationContract, match="hot_viral_samples blocked"):
        compile_generation_contract(plan, output_dir=tmp_path, input_paths={})
