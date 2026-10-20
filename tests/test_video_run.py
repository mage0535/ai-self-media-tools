from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from content_platform.video_run import (
    ArtifactSpec,
    GateEvidence,
    RunManifest,
    RunSpec,
    RunState,
    write_manifest_atomic,
)


def test_run_spec_and_manifest_are_immutable(tmp_path: Path) -> None:
    artifact = tmp_path / "video.mp4"
    artifact.write_bytes(b"video-v1")
    spec = RunSpec(
        run_id="run-001",
        revision=3,
        artifacts=(ArtifactSpec("video", artifact.resolve()),),
    )
    manifest = RunManifest.plan(spec)

    assert manifest.state is RunState.PLANNED
    assert manifest.artifact_sha256["video"] == (
        "0670119c180672c4807244d2a28a1b986906a6c748371d048a1499d260951831"
    )
    with pytest.raises(FrozenInstanceError):
        spec.revision = 4  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        manifest.state = RunState.RENDERING  # type: ignore[misc]
    with pytest.raises(TypeError):
        manifest.artifact_sha256["video"] = "forged"  # type: ignore[index]


def test_run_spec_rejects_noncanonical_or_pattern_paths(tmp_path: Path) -> None:
    relative = Path("video.mp4")
    with pytest.raises(ValueError, match="canonical absolute path"):
        ArtifactSpec("video", relative)
    with pytest.raises(ValueError, match="patterns"):
        ArtifactSpec("video", tmp_path / "*.mp4")


def _planned_manifest(tmp_path: Path) -> RunManifest:
    artifact = (tmp_path / "video.mp4").resolve()
    artifact.write_bytes(b"video-v1")
    return RunManifest.plan(
        RunSpec("run-001", 3, (ArtifactSpec("video", artifact),))
    )


def test_state_machine_only_allows_the_declared_sequence(tmp_path: Path) -> None:
    manifest = _planned_manifest(tmp_path)
    ordered_states = [
        state
        for state in RunState
        if state.name not in {"FAILED_RETRYABLE", "FAILED_TERMINAL", "BLOCKED_DEDUP", "DEGRADED_REQUIRES_REVIEW"}
    ]

    with pytest.raises(ValueError, match="illegal transition"):
        manifest.advance(RunState.RENDERING)

    for target in ordered_states[1:]:
        evidence = manifest.make_gate_evidence(target) if target.is_gate else None
        manifest = manifest.advance(target, evidence=evidence)

    assert manifest.state is RunState.HANDOFF_READY
    assert [item.gate for item in manifest.gate_evidence] == [
        RunState.DEDUP_GATED,
        RunState.MEDIA_GATED,
        RunState.VISUAL_GATED,
        RunState.AUDIO_GATED,
        RunState.COVER_GATED,
        RunState.PACKAGE_GATED,
    ]


def test_dedup_block_is_an_explicit_terminal_failure_state(tmp_path: Path) -> None:
    manifest = _planned_manifest(tmp_path)

    blocked = manifest.fail(RunState.BLOCKED_DEDUP, reason="historical duplicate")

    assert blocked.state is RunState.BLOCKED_DEDUP
    assert blocked.failure_reason == "historical duplicate"
    with pytest.raises(ValueError, match="terminal"):
        blocked.advance(RunState.CONTRACT_VALIDATED)


def test_gate_evidence_is_bound_to_run_revision_and_all_artifact_hashes(
    tmp_path: Path,
) -> None:
    manifest = _planned_manifest(tmp_path)
    evidence = manifest.make_gate_evidence(RunState.MEDIA_GATED)

    assert evidence.run_id == "run-001"
    assert evidence.revision == 3
    assert evidence.artifact_sha256 == manifest.artifact_sha256
    with pytest.raises(TypeError):
        evidence.artifact_sha256["video"] = "forged"  # type: ignore[index]

    wrong_run = GateEvidence(
        gate=RunState.MEDIA_GATED,
        run_id="another-run",
        revision=3,
        attempt_id="attempt-1",
        artifact_sha256=manifest.artifact_sha256,
    )
    for target in list(RunState)[1:6]:
        manifest = manifest.advance(target)
    manifest = manifest.advance(
        RunState.DEDUP_GATED,
        evidence=manifest.make_gate_evidence(RunState.DEDUP_GATED),
    )
    with pytest.raises(ValueError, match="does not match this run"):
        manifest.advance(RunState.MEDIA_GATED, evidence=wrong_run)


def test_any_artifact_hash_change_makes_all_gate_evidence_stale(
    tmp_path: Path,
) -> None:
    manifest = _planned_manifest(tmp_path)
    for target in list(RunState)[1:6]:
        manifest = manifest.advance(target)
    manifest = manifest.advance(
        RunState.DEDUP_GATED,
        evidence=manifest.make_gate_evidence(RunState.DEDUP_GATED),
    )
    evidence = manifest.make_gate_evidence(RunState.MEDIA_GATED)
    manifest = manifest.advance(RunState.MEDIA_GATED, evidence=evidence)
    assert manifest.is_gate_evidence_current(evidence)

    manifest.spec.artifacts[0].path.write_bytes(b"video-v2")
    refreshed = manifest.refresh_artifact_hashes()

    assert not refreshed.is_gate_evidence_current(evidence)
    assert refreshed.gate_evidence == manifest.gate_evidence


def test_manifest_json_is_atomically_replaced(tmp_path: Path) -> None:
    manifest = _planned_manifest(tmp_path)
    destination = tmp_path / "manifest.json"
    destination.write_text('{"old":true}', encoding="utf-8")

    write_manifest_atomic(manifest, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload == {
        "artifact_sha256": dict(manifest.artifact_sha256),
        "artifacts": [
            {
                "name": "video",
                "path": str(manifest.spec.artifacts[0].path),
                "role": "INPUT",
            }
        ],
        "attempt_id": "attempt-1",
        "failure_reason": None,
        "gate_evidence": [],
        "revision": 3,
        "run_id": "run-001",
        "state": "PLANNED",
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "manifest.json",
        "video.mp4",
    ]


def test_failed_atomic_replace_preserves_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _planned_manifest(tmp_path)
    destination = tmp_path / "manifest.json"
    destination.write_text('{"old":true}', encoding="utf-8")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("content_platform.video_run.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_manifest_atomic(manifest, destination)

    assert destination.read_text(encoding="utf-8") == '{"old":true}'
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "manifest.json",
        "video.mp4",
    ]


def test_expected_output_can_be_bound_only_after_renderer_creates_it(tmp_path: Path) -> None:
    from content_platform.video_run import ArtifactRole, file_sha256

    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    final = tmp_path / "release" / "video.mp4"
    spec = RunSpec(
        run_id="run-late-output",
        revision=1,
        artifacts=(
            ArtifactSpec("plan", plan, role=ArtifactRole.INPUT),
            ArtifactSpec("video", final, role=ArtifactRole.OUTPUT),
        ),
    )

    manifest = RunManifest.plan(spec)
    assert manifest.artifact_sha256 == {"plan": file_sha256(plan)}
    assert manifest.missing_outputs == ("video",)

    final.parent.mkdir()
    final.write_bytes(b"rendered-video")
    bound = manifest.bind_outputs()

    assert bound.missing_outputs == ()
    assert bound.artifact_sha256["video"] == file_sha256(final)


@pytest.mark.parametrize(
    "failure_state",
    ["FAILED_RETRYABLE", "FAILED_TERMINAL", "DEGRADED_REQUIRES_REVIEW"],
)
def test_run_can_enter_explicit_failure_terminal_without_advancing_success_path(
    tmp_path: Path, failure_state: str
) -> None:
    from content_platform.video_run import ArtifactSpec, RunManifest, RunSpec, RunState

    source = tmp_path / "plan.json"
    source.write_text("{}", encoding="utf-8")
    manifest = RunManifest.plan(
        RunSpec(
            run_id="run-failure",
            revision=1,
            artifacts=(ArtifactSpec("plan", source.resolve()),),
            attempt_id="attempt-003",
        )
    )

    failed = manifest.fail(RunState[failure_state], reason="checker timeout")
    assert failed.state is RunState[failure_state]
    assert failed.failure_reason == "checker timeout"
    with pytest.raises(ValueError, match="terminal"):
        failed.advance(RunState.CONTRACT_VALIDATED)


def test_gate_evidence_is_bound_to_attempt_identity(tmp_path: Path) -> None:
    from content_platform.video_run import ArtifactSpec, RunManifest, RunSpec, RunState

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    manifest = RunManifest.plan(
        RunSpec(
            run_id="run-attempt",
            revision=2,
            artifacts=(ArtifactSpec("video", video.resolve()),),
            attempt_id="attempt-007",
        )
    )
    evidence = manifest.make_gate_evidence(RunState.MEDIA_GATED)

    assert evidence.attempt_id == "attempt-007"
    assert manifest.to_dict()["attempt_id"] == "attempt-007"
