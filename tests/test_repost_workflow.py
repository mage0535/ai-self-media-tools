from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from content_platform.repost_workflow import (
    RepostRun,
    RepostState,
    SourceLedger,
    StageDAG,
    StageLease,
    StageName,
    TransformationLedger,
    UnknownStateError,
    WorkflowError,
    content_cache_key,
    validate_handoff_directory,
    validate_narration_manifest,
    validate_similarity_report,
    validate_timeline,
)


def test_state_machine_accepts_required_handoff_and_rejects_publish_without_human(tmp_path):
    run = RepostRun(tmp_path)
    run.data["publishable"] = False
    run.data["manual_publish_required"] = True
    run._save()
    for state in (
        RepostState.SOURCE_REGISTERED,
        RepostState.SCRIPT_READY,
        RepostState.TTS_READY,
        RepostState.VISUAL_PLAN_READY,
        RepostState.COVER_READY,
        RepostState.INTRO_OUTRO_READY,
        RepostState.INTERNAL_DUP_CHECKED,
        RepostState.PREFLIGHT_PASSED,
        RepostState.RENDERING,
        RepostState.MUXED,
        RepostState.DEEP_QA_PASSED,
        RepostState.HANDOFF_READY,
        RepostState.RIGHTS_EXTERNAL_PENDING,
    ):
        run.transition(state)
    assert run.state is RepostState.RIGHTS_EXTERNAL_PENDING
    with pytest.raises(WorkflowError):
        run.transition(RepostState.PUBLISHED_USER_VERIFIED)


def test_unknown_checkpoint_state_fails_closed(tmp_path):
    (tmp_path / "checkpoint.json").write_text(json.dumps({"schema_version": "repost_workflow_v1", "state": "MADE_UP", "stages": {}}), encoding="utf-8")
    with pytest.raises(UnknownStateError):
        RepostRun(tmp_path)


def test_dag_closure_and_checkpoint_cache_recovery(tmp_path):
    run = RepostRun(tmp_path)
    source = tmp_path / "source.txt"
    output = tmp_path / "out.txt"
    source.write_text("one", encoding="utf-8")
    run.execute_stage(StageName.SOURCE_REGISTER, input_paths=[source], output_paths=[output], cache_key="source-v1", func=lambda: output.write_text("done", encoding="utf-8"))
    assert run.dag.record(StageName.SOURCE_REGISTER)["cache_hit"] is False
    first = run.dag.record(StageName.SOURCE_REGISTER)["output_sha256"]
    reopened = RepostRun(tmp_path)
    reopened.execute_stage(StageName.SOURCE_REGISTER, input_paths=[source], output_paths=[output], cache_key="source-v1", func=lambda: pytest.fail("cache should be reused"))
    assert reopened.dag.record(StageName.SOURCE_REGISTER)["cache_hit"] is True
    assert reopened.dag.record(StageName.SOURCE_REGISTER)["output_sha256"] == first
    assert StageName.RENDERING.value in StageDAG().dependency_closure(StageName.COVER)


def test_cache_key_changes_on_one_byte_and_runtime_versions():
    base = {"source_asset_sha256": "same", "browser_version_or_binary_hash": "browser-a", "font_hash": "font-a"}
    assert content_cache_key(**base) != content_cache_key(**{**base, "source_asset_sha256": "same2"})
    assert content_cache_key(**base) != content_cache_key(**{**base, "browser_version_or_binary_hash": "browser-b"})
    assert content_cache_key(**base) != content_cache_key(**{**base, "font_hash": "font-b"})
    assert content_cache_key(**base) != content_cache_key(**{**base, "renderer_source_hash": "renderer-b"})


def test_stage_lease_rejects_live_owner_and_recovers_stale(tmp_path):
    first = StageLease(tmp_path, "rendering", ttl_seconds=1, owner_pid=os.getpid())
    first.acquire(input_key="a", output_dir=tmp_path)
    with pytest.raises(WorkflowError):
        StageLease(tmp_path, "rendering", ttl_seconds=1, owner_pid=os.getpid()).acquire(input_key="b", output_dir=tmp_path)
    payload = json.loads((tmp_path / ".leases" / "rendering.lock").read_text(encoding="utf-8"))
    payload["owner_pid"] = 99999999
    payload["lease_expires_at"] = time.time() - 10
    (tmp_path / ".leases" / "rendering.lock").write_text(json.dumps(payload), encoding="utf-8")
    recovered = StageLease(tmp_path, "rendering", ttl_seconds=1, owner_pid=os.getpid())
    recovered.acquire(input_key="c", output_dir=tmp_path)
    assert recovered.heartbeat() is True
    assert recovered.release() is True


def test_source_ledger_cannot_be_marked_authorized(tmp_path):
    media = tmp_path / "source.bin"
    media.write_bytes(b"not-media")
    # SourceLedger validation is intentionally independent of acquisition; use a
    # manually constructed ledger to test the rights boundary without ffprobe.
    ledger = SourceLedger("id", "tiktok", "https://tiktok.example/v", "cid", "creator", "title", "now", "a" * 64, 3.0, "720x1280", source_manifest_path="source_manifest.json")
    assert ledger.validate() == []
    ledger.rights_status = "authorized"
    assert "rights_status_must_remain_external_manual_pending" in ledger.validate()


def test_timeline_and_narration_fail_closed_on_edges(tmp_path):
    valid = {"intro": {"start": 0, "duration_actual": 1.1}, "main_content": {"start": 1.1, "end": 7.5}, "outro": {"start_actual": 7.5, "duration_actual": 2.5, "minimum_duration": 2}, "last_narration_end": 7.0, "final_video_duration": 10.0}
    assert validate_timeline(valid, 10.0)["passed"] is True
    invalid = {**valid, "intro": {"start": 0, "duration_actual": 0.5}}
    assert "intro_duration_below_one_second" in validate_timeline(invalid, 10.0)["failures"]
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    narration = {"audio_path": str(audio), "audio_sha256": "wrong", "segments": [{"start": 1, "end": 2, "text": "旁白"}]}
    assert "narration_audio_hash_mismatch" in validate_narration_manifest(narration, 10.0)["failures"]


def test_similarity_high_match_is_blocked():
    report = {"reviewer_decision": "BLOCKED_INTERNAL_SIMILARITY", "source_video_sha256": "a", "candidate_video_sha256": "b", "source_frame_fingerprint": "a", "candidate_frame_fingerprint": "b", "source_audio_fingerprint": "a", "candidate_audio_fingerprint": "b", "source_segment_to_output_segment_mapping": [], "similarity_scores": {"frame": 0.99}, "threshold_version": "v1", "model_version": "v1", "transformation_ledger": {}}
    result = validate_similarity_report(report)
    assert result["passed"] is False
    assert "BLOCKED_INTERNAL_SIMILARITY" in result["failures"]


def test_fixture_handoff_and_tamper_gate(tmp_path):
    from scripts.repost_pipeline_runner import run_fixture

    result = run_fixture(tmp_path)
    assert result["state"] == RepostState.RIGHTS_EXTERNAL_PENDING.value
    assert result["handoff_validation"]["passed"] is True
    final = tmp_path / "final.mp4"
    original = final.read_bytes()
    final.write_bytes(original + b"tamper")
    failed = validate_handoff_directory(tmp_path)
    assert failed["passed"] is False
    assert any("artifact_hash_mismatch:final.mp4" == item for item in failed["failures"])


def test_cover_retry_preserves_scene_render_cache(tmp_path):
    from scripts.repost_pipeline_runner import run_fixture

    run_fixture(tmp_path)
    first = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    first_render = first["stages"][StageName.RENDERING.value]
    run_fixture(tmp_path, retry_stage=StageName.COVER.value)
    second = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert second["stages"][StageName.RENDERING.value]["cache_hit"] is True
    assert second["stages"][StageName.RENDERING.value]["output_sha256"] == first_render["output_sha256"]


def test_transformation_ledger_requires_manual_review_fields():
    ledger = TransformationLedger()
    ledger.add(segment="s1", edit_type="reorder", reason="narrative", content_impact="new context", quality_check="checked")
    assert ledger.validate() == []
    ledger.entries[0]["reason"] = ""
    assert "entry_0_reason_missing" in ledger.validate()
