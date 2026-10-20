from __future__ import annotations

from pathlib import Path

import pytest


def _rendered_manifest(tmp_path: Path):
    from content_platform.video_run import ArtifactRole, ArtifactSpec, RunManifest, RunSpec, RunState

    plan = tmp_path / "plan.json"
    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    plan.write_text("{}", encoding="utf-8")
    video.write_bytes(b"video-v1")
    cover.write_bytes(b"cover-v1")
    manifest = RunManifest.plan(
        RunSpec(
            run_id="release-001",
            revision=2,
            attempt_id="attempt-4",
            artifacts=(
                ArtifactSpec("plan", plan, ArtifactRole.INPUT),
                ArtifactSpec("video", video, ArtifactRole.OUTPUT),
                ArtifactSpec("cover", cover, ArtifactRole.OUTPUT),
            ),
        )
    )
    for state in (
        RunState.CONTRACT_VALIDATED,
        RunState.ASSETS_VALIDATED,
        RunState.PREVIEW_VALIDATED,
        RunState.RENDERING,
        RunState.RENDERED_UNVERIFIED,
    ):
        manifest = manifest.advance(state)
    return manifest, video, cover


def test_bind_checker_result_rejects_unapproved_checker_identity(tmp_path: Path) -> None:
    from content_platform.video_release_gate import bind_checker_result

    manifest, _, _ = _rendered_manifest(tmp_path)

    with pytest.raises(ValueError, match="unsupported checker"):
        bind_checker_result(
            manifest,
            checker="attacker",
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )


def test_release_gate_requires_bound_dedup_checker_result(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff

    manifest, _, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }
    checks.pop("dedup")

    with pytest.raises(ReleaseBlocked, match="dedup checker result missing"):
        release_to_handoff(manifest, checks)


def test_bind_checker_result_requires_evidence_sha256(tmp_path: Path) -> None:
    from content_platform.video_release_gate import bind_checker_result

    manifest, _, _ = _rendered_manifest(tmp_path)

    with pytest.raises(ValueError, match="evidence_sha256"):
        bind_checker_result(
            manifest,
            checker="media",
            passed=True,
            failures=[],
            evidence_sha256="",
        )


def test_bind_checker_result_rejects_non_boolean_status(tmp_path: Path) -> None:
    from content_platform.video_release_gate import bind_checker_result

    manifest, _, _ = _rendered_manifest(tmp_path)

    with pytest.raises(TypeError, match="passed"):
        bind_checker_result(
            manifest,
            checker="media",
            passed=1,  # type: ignore[arg-type]
            failures=[],
            evidence_sha256="a" * 64,
        )


def test_release_gate_rejects_fabricated_checker_mapping(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff

    manifest, _, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }
    checks["media"] = dict(checks["media"])

    with pytest.raises(ReleaseBlocked, match="not bound"):
        release_to_handoff(manifest, checks)


def test_release_gate_requires_all_six_identity_bound_checker_results(tmp_path: Path) -> None:
    from content_platform.video_release_gate import bind_checker_result, release_to_handoff
    from content_platform.video_run import RunState

    manifest, _, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }

    released = release_to_handoff(manifest, checks)
    assert released.state is RunState.HANDOFF_READY
    assert len(released.gate_evidence) == 6


def test_dedup_gate_evidence_persists_checker_evidence_hash(tmp_path: Path) -> None:
    from content_platform.video_release_gate import bind_checker_result, release_to_handoff
    from content_platform.video_run import RunState

    manifest, _, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256=("d" if name == "dedup" else "a") * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }

    released = release_to_handoff(manifest, checks)
    dedup = next(item for item in released.gate_evidence if item.gate is RunState.DEDUP_GATED)

    assert dedup.evidence_sha256 == "d" * 64
    serialized = next(
        item for item in released.to_dict()["gate_evidence"] if item["gate"] == "DEDUP_GATED"
    )
    assert serialized["evidence_sha256"] == "d" * 64


def test_release_gate_fails_closed_on_checker_failure(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff

    manifest, _, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=name != "audio",
            failures=[] if name != "audio" else ["bgm_lufs_out_of_range"],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }

    with pytest.raises(ReleaseBlocked, match="audio"):
        release_to_handoff(manifest, checks)


def test_release_gate_rejects_stale_evidence_after_video_changes(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff

    manifest, video, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }
    video.write_bytes(b"video-v2")
    changed = manifest.refresh_artifact_hashes()

    with pytest.raises(ReleaseBlocked, match="artifact hashes"):
        release_to_handoff(changed, checks)


def test_release_gate_rehashes_again_before_final_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff
    from content_platform.video_run import RunManifest, RunState

    manifest, video, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }
    original_advance = RunManifest.advance

    def mutate_during_promotion(self, target, *, evidence=None):
        if target is RunState.MEDIA_GATED:
            video.write_bytes(b"video-mutated-during-promotion")
        return original_advance(self, target, evidence=evidence)

    monkeypatch.setattr(RunManifest, "advance", mutate_during_promotion)

    with pytest.raises(ReleaseBlocked, match="changed on disk"):
        release_to_handoff(manifest, checks)


def test_release_gate_rehashes_disk_artifacts_before_promotion(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked, bind_checker_result, release_to_handoff

    manifest, video, _ = _rendered_manifest(tmp_path)
    checks = {
        name: bind_checker_result(
            manifest,
            checker=name,
            passed=True,
            failures=[],
            evidence_sha256="a" * 64,
        )
        for name in ("dedup", "media", "visual", "audio", "cover", "package")
    }
    video.write_bytes(b"video-mutated-after-checks")

    with pytest.raises(ReleaseBlocked, match="changed on disk"):
        release_to_handoff(manifest, checks)
