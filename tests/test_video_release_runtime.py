from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont
import pytest


def _make_video(path: Path, *, duration: int = 12) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=360x640:rate=24:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=44100:duration={duration}",
            "-shortest",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def _make_valid_cover(path: Path, size: tuple[int, int] = (1080, 1080)) -> None:
    image = Image.new("RGB", size, "#071421")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 36):
        draw.rectangle((0, y, size[0], min(size[1] - 1, y + 35)), fill=(10, 30 + y // 72 % 35, 55))
    draw.ellipse((680, 430, 930, 680), fill="#ef8354", outline="white", width=10)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 82)
    draw.text((90, 180), "VERIFY FIRST", font=font, fill="white")
    image.save(path)


def _valid_dedup_evidence(candidate: Path) -> dict[str, object]:
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return {
        "passed": True,
        "stage": "post_render",
        "final_mp4_sha256": digest,
        "fingerprints": {
            "sha256": digest,
            "frame_phashes": ["1" * 16],
            "audio_fingerprint": "2" * 64,
        },
        "history_index": {
            "status": "available",
            "path": "/trusted/history.jsonl",
            "entry_count": 0,
        },
        "transform": {"kind": "localized_caption_edit", "description": "localized captions"},
        "rights": {"basis": "licensed", "reference": "license-42"},
        "post_render_verification": {"required": True, "passed": True},
        "failures": [],
    }


def _valid_audio_evidence(
    candidate: Path, voiceover: Path, sfx: Path, *, duration: float = 30.0
) -> dict[str, object]:
    return {
        "route": "sfx_only",
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "stems": [
            {"role": "voiceover", "path": str(voiceover), "sha256": hashlib.sha256(voiceover.read_bytes()).hexdigest(), "coverage_ratio": 1.0},
            {"role": "sound_effects", "path": str(sfx), "sha256": hashlib.sha256(sfx.read_bytes()).hexdigest(), "coverage_ratio": 1.0},
        ],
        "coverage_ratio": 1.0,
        "windows": {
            "opening": {"start_seconds": 0.0, "end_seconds": duration * 0.2, "coverage_ratio": 1.0, "stem_roles": ["voiceover", "sound_effects"]},
            "middle": {"start_seconds": duration * 0.4, "end_seconds": duration * 0.6, "coverage_ratio": 1.0, "stem_roles": ["voiceover", "sound_effects"]},
            "ending": {"start_seconds": duration * 0.8, "end_seconds": duration, "coverage_ratio": 1.0, "stem_roles": ["voiceover", "sound_effects"]},
        },
        "final_loudness": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.2},
    }


def test_audio_evidence_checker_requires_candidate_bound_stems_coverage_windows_and_loudness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_platform import video_release_runtime

    candidate = tmp_path / "final.mp4"
    voiceover = tmp_path / "voiceover.wav"
    sfx = tmp_path / "sfx.wav"
    candidate.write_bytes(b"candidate")
    voiceover.write_bytes(b"voice")
    sfx.write_bytes(b"effects")
    monkeypatch.setattr(video_release_runtime, "probe_video", lambda _: {"duration_seconds": 30.0})
    monkeypatch.setattr(video_release_runtime, "_probe_loudness", lambda _: {"integrated_lufs": -16.0, "true_peak_dbtp": -1.2})

    result = video_release_runtime._audio_evidence_check(candidate, {"audio_evidence": _valid_audio_evidence(candidate, voiceover, sfx)})

    assert result["failures"] == []


def test_audio_evidence_checker_fails_closed_when_evidence_is_missing(tmp_path: Path) -> None:
    from content_platform.video_release_runtime import _audio_evidence_check

    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"candidate")

    assert _audio_evidence_check(candidate, {})["failures"] == ["audio_evidence_missing"]


def test_visual_failures_accepts_only_sha_bound_element_motion_evidence() -> None:
    from content_platform.video_release_runtime import _visual_failures

    measured = {
        "mean_delta": 0.065,
        "sustained_motion_ratio": 0.75,
        "active_ratio": 0.38,
        "peak_count": 26,
    }
    assert "sustained_motion_below_threshold" in _visual_failures(
        measured, candidate_sha256="video-sha", render_manifest={}
    )

    evidence = {
        "passed": True,
        "motion_gate_mode": "element_motion",
        "candidate_sha256": "video-sha",
        "fallback_shots": [],
        "element_motion_shots": ["shot_01A"],
        "motion": measured,
    }
    assert _visual_failures(
        measured,
        candidate_sha256="video-sha",
        render_manifest={"render_quality_evidence": evidence},
    ) == []
    evidence["candidate_sha256"] = "wrong-sha"
    assert "sustained_motion_below_threshold" in _visual_failures(
        measured,
        candidate_sha256="video-sha",
        render_manifest={"render_quality_evidence": evidence},
    )


def test_visual_failures_accepts_stable_background_with_local_roi_motion():
    from content_platform.video_release_runtime import _visual_failures

    measured = {
        "mean_delta": 0.02121,
        "sustained_motion_ratio": 0.29054,
        "active_ratio": 0.18919,
        "peak_count": 19,
    }
    evidence = {
        "passed": True,
        "motion_gate_mode": "element_motion",
        "candidate_sha256": "video-sha",
        "fallback_shots": [],
        "element_motion_shots": ["shot_01B"],
        "motion": measured,
        "spatial_motion": {
            "passed": True,
            "background_stable": True,
            "business_roi_active_ratio": 0.09962,
            "failures": [],
        },
    }
    assert _visual_failures(
        measured,
        candidate_sha256="video-sha",
        render_manifest={"render_quality_evidence": evidence},
    ) == []

    low_global_but_valid_local = {
        **measured,
        "mean_delta": 0.01176,
        "active_ratio": 0.09877,
        "sustained_motion_ratio": 0.46914,
        "peak_count": 16,
    }
    evidence["motion"] = low_global_but_valid_local
    evidence["spatial_motion"]["business_roi_active_ratio"] = 0.23693
    evidence["spatial_motion"]["moving_area_ratio_p95"] = 0.00997
    assert _visual_failures(
        low_global_but_valid_local,
        candidate_sha256="video-sha",
        render_manifest={"render_quality_evidence": evidence},
    ) == []

    evidence["spatial_motion"]["background_stable"] = False
    assert "sustained_motion_below_threshold" in _visual_failures(
        measured,
        candidate_sha256="video-sha",
        render_manifest={"render_quality_evidence": evidence},
    )


def test_audio_evidence_checker_rejects_true_peak_above_minus_one_dbtp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_platform import video_release_runtime

    candidate = tmp_path / "final.mp4"
    voiceover = tmp_path / "voiceover.wav"
    sfx = tmp_path / "sfx.wav"
    candidate.write_bytes(b"candidate")
    voiceover.write_bytes(b"voice")
    sfx.write_bytes(b"effects")
    evidence = _valid_audio_evidence(candidate, voiceover, sfx)
    evidence["final_loudness"]["true_peak_dbtp"] = 0.01
    monkeypatch.setattr(video_release_runtime, "probe_video", lambda _: {"duration_seconds": 30.0})
    monkeypatch.setattr(video_release_runtime, "_probe_loudness", lambda _: {"integrated_lufs": -16.0, "true_peak_dbtp": 0.01})

    result = video_release_runtime._audio_evidence_check(candidate, {"audio_evidence": evidence})

    assert "true_peak_above_minus_one_dbtp" in result["failures"]


def test_audio_evidence_checker_rejects_stem_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_platform import video_release_runtime

    candidate = tmp_path / "final.mp4"
    voiceover = tmp_path / "voiceover.wav"
    sfx = tmp_path / "sfx.wav"
    candidate.write_bytes(b"candidate")
    voiceover.write_bytes(b"voice")
    sfx.write_bytes(b"effects")
    evidence = _valid_audio_evidence(candidate, voiceover, sfx)
    evidence["stems"][0]["sha256"] = "0" * 64
    monkeypatch.setattr(video_release_runtime, "probe_video", lambda _: {"duration_seconds": 30.0})
    monkeypatch.setattr(video_release_runtime, "_probe_loudness", lambda _: {"integrated_lufs": -16.0, "true_peak_dbtp": -1.2})

    result = video_release_runtime._audio_evidence_check(candidate, {"audio_evidence": evidence})

    assert "stem_hash_mismatch:voiceover" in result["failures"]


def test_audio_evidence_checker_computes_coverage_from_actual_stem_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_platform import video_release_runtime

    candidate = tmp_path / "final.mp4"
    voiceover = tmp_path / "voiceover.wav"
    sfx = tmp_path / "sfx.wav"
    candidate.write_bytes(b"candidate")
    voiceover.write_bytes(b"voice")
    sfx.write_bytes(b"effects")
    evidence = _valid_audio_evidence(candidate, voiceover, sfx)

    def fake_probe(path: Path):
        return {"duration_seconds": 10.0 if Path(path) == voiceover else 30.0}

    monkeypatch.setattr(video_release_runtime, "probe_video", fake_probe)
    monkeypatch.setattr(video_release_runtime, "_probe_loudness", lambda _: {"integrated_lufs": -16.0, "true_peak_dbtp": -1.2})

    result = video_release_runtime._audio_evidence_check(candidate, {"audio_evidence": evidence})

    assert "stem_coverage_incomplete:voiceover" in result["failures"]
    assert "stem_coverage_mismatch:voiceover" in result["failures"]


def test_dedup_checker_accepts_complete_candidate_bound_evidence(tmp_path: Path) -> None:
    from content_platform.video_release_runtime import _dedup_check

    candidate = tmp_path / "final.mp4"
    evidence_path = tmp_path / "dedup_evidence.json"
    candidate.write_bytes(b"candidate")
    evidence_path.write_text(json.dumps(_valid_dedup_evidence(candidate)), encoding="utf-8")

    result = _dedup_check(candidate, evidence_path=evidence_path, required=True)

    assert result["failures"] == []
    assert result["required"] is True
    assert result["final_mp4_sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        (lambda evidence: evidence.update(passed=1), "dedup_not_passed"),
        (lambda evidence: evidence.update(final_mp4_sha256="0" * 64), "final_mp4_sha256_mismatch"),
        (lambda evidence: evidence.update(fingerprints={}), "fingerprints_incomplete_or_mismatched"),
        (lambda evidence: evidence.update(history_index={}), "history_incomplete"),
        (lambda evidence: evidence.update(transform={}), "transform_incomplete"),
        (lambda evidence: evidence.update(rights={}), "rights_incomplete"),
    ],
)
def test_dedup_checker_rejects_non_boolean_or_incomplete_evidence(
    tmp_path: Path, mutation, expected_failure: str
) -> None:
    from content_platform.video_release_runtime import _dedup_check

    candidate = tmp_path / "final.mp4"
    evidence_path = tmp_path / "dedup_evidence.json"
    candidate.write_bytes(b"candidate")
    evidence = _valid_dedup_evidence(candidate)
    mutation(evidence)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    result = _dedup_check(candidate, evidence_path=evidence_path, required=True)

    assert expected_failure in result["failures"]


def test_create_preview_writes_real_at_most_ten_second_mp4(tmp_path: Path) -> None:
    from content_platform.video_release_runtime import create_preview
    from content_platform.video_artifact import probe_video

    candidate = tmp_path / "final.mp4"
    preview = tmp_path / "preview.mp4"
    _make_video(candidate, duration=12)

    evidence = create_preview(candidate, preview)

    probed = probe_video(preview)
    assert preview.is_file()
    assert 0 < probed["duration_seconds"] <= 10.1
    assert evidence["duration_seconds"] == probed["duration_seconds"]
    assert evidence["sha256"] == hashlib.sha256(preview.read_bytes()).hexdigest()
    assert evidence["source_sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()


def test_release_candidate_runs_six_real_checkers_and_atomically_promotes(tmp_path: Path) -> None:
    from content_platform.video_release_runtime import _probe_loudness, release_rendered_candidate
    from content_platform.video_run import (
        ArtifactRole,
        ArtifactSpec,
        RunManifest,
        RunSpec,
        RunState,
    )

    plan = tmp_path / "plan.json"
    script = tmp_path / "script.txt"
    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    cover_evidence = tmp_path / "cover_evidence.json"
    trusted = tmp_path / "trusted_run_manifest.json"
    plan.write_text("{}", encoding="utf-8")
    script.write_text("eight real beats", encoding="utf-8")
    _make_video(video, duration=12)
    voiceover = tmp_path / "voiceover.wav"
    sfx = tmp_path / "sfx.wav"
    for stem in (voiceover, sfx):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", str(stem)],
            check=True,
            timeout=60,
        )
    _make_valid_cover(cover)
    background = tmp_path / "background.png"
    _make_valid_cover(background)
    cover_evidence.write_text(
        json.dumps(
            {
                "platform": "bilibili",
                "layout_key": "evidence_interface",
                "hook": "VERIFY FIRST",
                "title_en": "VERIFY FIRST",
                "conflict_or_payoff": "before and after",
                "content_match_reason": "matches the rendered workflow",
                "background_provenance": {
                    "path": str(background),
                    "source": "test_fixture",
                    "visible_required": True,
                },
                "renderer": "test_fixture",
                "independent_render": True,
                "focal_subjects": ["workflow"],
                "safe_zone_verified": True,
                "degraded": False,
                "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    manifest = RunManifest.plan(
        RunSpec(
            run_id="release-runtime-001",
            revision=1,
            artifacts=(
                ArtifactSpec("plan", plan.resolve(), ArtifactRole.INPUT),
                ArtifactSpec("script", script.resolve(), ArtifactRole.INPUT),
                ArtifactSpec("video", video.resolve(), ArtifactRole.OUTPUT),
                ArtifactSpec("cover", cover.resolve(), ArtifactRole.OUTPUT),
            ),
        )
    )
    manifest = manifest.advance(RunState.CONTRACT_VALIDATED)
    manifest = manifest.advance(RunState.ASSETS_VALIDATED)

    released = release_rendered_candidate(
        manifest,
        output_dir=tmp_path,
        candidate=video,
        cover=cover,
        cover_evidence=cover_evidence,
        platform="bilibili",
        render_manifest={
            "subtitle": {"width": 360, "height": 640},
            "audio_evidence": {
                **_valid_audio_evidence(video, voiceover, sfx, duration=12.0),
                "final_loudness": _probe_loudness(video),
            },
        },
        trusted_manifest_path=trusted,
    )

    assert released.state is RunState.HANDOFF_READY
    from content_platform.media import MediaBridge

    assert MediaBridge._validate_trusted_video_manifest(tmp_path)["state"] == "HANDOFF_READY"
    assert json.loads(trusted.read_text(encoding="utf-8"))["state"] == "HANDOFF_READY"
    preview_probe = json.loads((tmp_path / "preview_evidence.json").read_text(encoding="utf-8"))["probe"]
    assert 0 < preview_probe["duration_seconds"] <= 10.1
    assert [item.gate.value for item in released.gate_evidence] == [
        "DEDUP_GATED",
        "MEDIA_GATED",
        "VISUAL_GATED",
        "AUDIO_GATED",
        "COVER_GATED",
        "PACKAGE_GATED",
    ]
    for checker in ("dedup", "media", "visual", "audio", "cover", "package"):
        path = tmp_path / f"{checker}_checker_evidence.json"
        assert path.is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["checker"] == checker
        assert len(payload["artifact_sha256"]) == 64
        assert len(payload["evidence_sha256"]) == 64
        canonical = dict(payload)
        declared = canonical.pop("evidence_sha256")
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert declared == hashlib.sha256(encoded).hexdigest()


def _assets_validated_manifest(tmp_path: Path, video: Path, cover: Path):
    from content_platform.video_run import ArtifactRole, ArtifactSpec, RunManifest, RunSpec, RunState

    plan = tmp_path / "failure-plan.json"
    plan.write_text("{}", encoding="utf-8")
    manifest = RunManifest.plan(
        RunSpec(
            run_id="release-failure-001",
            revision=1,
            artifacts=(
                ArtifactSpec("plan", plan.resolve(), ArtifactRole.INPUT),
                ArtifactSpec("video", video.resolve(), ArtifactRole.OUTPUT),
                ArtifactSpec("cover", cover.resolve(), ArtifactRole.OUTPUT),
            ),
        )
    )
    return manifest.advance(RunState.CONTRACT_VALIDATED).advance(RunState.ASSETS_VALIDATED)


def test_repost_release_persists_blocked_dedup_when_evidence_is_missing(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked
    from content_platform.video_release_runtime import release_rendered_candidate

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    cover_evidence = tmp_path / "cover_evidence.json"
    trusted = tmp_path / "trusted_run_manifest.json"
    _make_video(video, duration=12)
    Image.new("RGB", (1080, 1080), "navy").save(cover)
    cover_evidence.write_text(
        json.dumps(
            {
                "platform": "bilibili",
                "layout_key": "evidence_interface",
                "hook": "real hook",
                "conflict_or_payoff": "before and after",
                "content_match_reason": "matches the rendered workflow",
                "focal_subjects": ["workflow"],
                "safe_zone_verified": True,
                "degraded": False,
            }
        ),
        encoding="utf-8",
    )
    manifest = _assets_validated_manifest(tmp_path, video, cover)

    with pytest.raises(ReleaseBlocked, match="dedup"):
        release_rendered_candidate(
            manifest,
            output_dir=tmp_path,
            candidate=video,
            cover=cover,
            cover_evidence=cover_evidence,
            platform="bilibili",
            render_manifest={"selected_pipeline": "localized_repost_video"},
            trusted_manifest_path=trusted,
        )

    failed = json.loads(trusted.read_text(encoding="utf-8"))
    assert failed["state"] == "BLOCKED_DEDUP"
    assert "dedup checker failed" in failed["failure_reason"]


def test_release_candidate_persists_terminal_failure_reason_for_checker_rejection(tmp_path: Path) -> None:
    from content_platform.video_release_gate import ReleaseBlocked
    from content_platform.video_release_runtime import release_rendered_candidate

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    cover_evidence = tmp_path / "cover_evidence.json"
    trusted = tmp_path / "trusted_run_manifest.json"
    _make_video(video, duration=2)
    Image.new("RGB", (320, 320), "navy").save(cover)
    cover_evidence.write_text("{}", encoding="utf-8")
    manifest = _assets_validated_manifest(tmp_path, video, cover)

    with pytest.raises(ReleaseBlocked):
        release_rendered_candidate(
            manifest,
            output_dir=tmp_path,
            candidate=video,
            cover=cover,
            cover_evidence=cover_evidence,
            platform="bilibili",
            render_manifest={"subtitle": {}},
            trusted_manifest_path=trusted,
        )

    failed = json.loads(trusted.read_text(encoding="utf-8"))
    assert failed["state"] == "FAILED_TERMINAL"
    assert "checker failed" in failed["failure_reason"]


def test_release_candidate_persists_retryable_failure_when_preview_tool_cannot_decode(tmp_path: Path) -> None:
    from content_platform.video_release_runtime import release_rendered_candidate

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    cover_evidence = tmp_path / "cover_evidence.json"
    trusted = tmp_path / "trusted_run_manifest.json"
    video.write_bytes(b"not-a-video")
    Image.new("RGB", (1080, 1080), "navy").save(cover)
    cover_evidence.write_text("{}", encoding="utf-8")
    manifest = _assets_validated_manifest(tmp_path, video, cover)

    with pytest.raises(RuntimeError):
        release_rendered_candidate(
            manifest,
            output_dir=tmp_path,
            candidate=video,
            cover=cover,
            cover_evidence=cover_evidence,
            platform="bilibili",
            render_manifest={"subtitle": {}},
            trusted_manifest_path=trusted,
        )

    failed = json.loads(trusted.read_text(encoding="utf-8"))
    assert failed["state"] == "FAILED_RETRYABLE"
    assert "ffmpeg" in failed["failure_reason"]
