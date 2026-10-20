"""Runtime adapters that bind real video checks to the release gate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Mapping

from .delivery_manifest import build_delivery_manifest
from .video_artifact import (
    HIGH_QUALITY_ACTIVE_RATIO_THRESHOLD,
    HIGH_QUALITY_MEAN_MOTION_THRESHOLD,
    HIGH_QUALITY_MIN_PEAKS,
    HIGH_QUALITY_SUSTAINED_MOTION_RATIO_THRESHOLD,
    measure_motion_evidence,
    probe_video,
    verify_artifact,
    verify_final_pixels,
)
from .video_release_gate import (
    DedupBlocked,
    ReleaseBlocked,
    bind_checker_result,
    release_to_handoff,
)
from .video_run import RunManifest, RunState, write_manifest_atomic


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_preview(candidate: Path, destination: Path) -> dict[str, object]:
    """Create and independently probe a low-cost preview of at most ten seconds."""
    candidate = Path(candidate).resolve()
    destination = Path(destination).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"preview source missing: {candidate}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=".mp4",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        process = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(candidate),
                "-t",
                "10",
                "-vf",
                "scale='min(540,iw)':-2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if process.returncode:
            detail = (process.stderr or "unknown ffmpeg error")[-1000:]
            raise RuntimeError(f"ffmpeg preview failed: {detail}")
        probe = probe_video(temporary)
        duration = float(probe.get("duration_seconds") or 0)
        if duration <= 0 or duration > 10.1:
            raise RuntimeError(f"preview duration invalid: {duration}")
        os.replace(temporary, destination)
        return {
            "artifact": str(destination),
            "duration_seconds": duration,
            "probe": probe,
            "sha256": _sha256(destination),
            "source": str(candidate),
            "source_sha256": _sha256(candidate),
        }
    finally:
        temporary.unlink(missing_ok=True)


def _write_evidence(path: Path, payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    canonical = dict(payload)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    document = {**canonical, "evidence_sha256": digest}
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return document, digest


def _visual_failures(
    result: Mapping[str, object], *, candidate_sha256: str, render_manifest: Mapping[str, object]
) -> list[str]:
    evidence = render_manifest.get("render_quality_evidence")
    if isinstance(evidence, Mapping):
        recorded_motion = evidence.get("motion")
        motion_matches = isinstance(recorded_motion, Mapping) and all(
            abs(float(recorded_motion.get(field) or 0) - float(result.get(field) or 0)) <= 0.0001
            for field in ("mean_delta", "active_ratio", "sustained_motion_ratio")
        ) and int(recorded_motion.get("peak_count") or 0) == int(result.get("peak_count") or 0)
        spatial_motion = evidence.get("spatial_motion")
        stable_background_with_local_motion = bool(
            isinstance(spatial_motion, Mapping)
            and spatial_motion.get("passed") is True
            and spatial_motion.get("background_stable") is True
            and not spatial_motion.get("failures")
            and float(spatial_motion.get("business_roi_active_ratio") or 0) >= 0.05
            and (
                spatial_motion.get("moving_area_ratio_p95") is None
                or float(spatial_motion.get("moving_area_ratio_p95") or 1) <= 0.25
            )
        )
        element_motion_valid = bool(
            evidence.get("passed") is True
            and evidence.get("motion_gate_mode") == "element_motion"
            and evidence.get("candidate_sha256") == candidate_sha256
            and not evidence.get("fallback_shots")
            and evidence.get("element_motion_shots")
            and motion_matches
            and (
                float(result.get("mean_delta") or 0) >= HIGH_QUALITY_MEAN_MOTION_THRESHOLD
                or stable_background_with_local_motion
            )
            and (
                float(result.get("active_ratio") or 0) >= 0.15
                or stable_background_with_local_motion
            )
            and (
                float(result.get("sustained_motion_ratio") or 0) >= 0.50
                or stable_background_with_local_motion
            )
            and int(result.get("peak_count") or 0) >= HIGH_QUALITY_MIN_PEAKS
        )
        if element_motion_valid:
            return []
    failures = []
    if float(result.get("mean_delta") or 0) < HIGH_QUALITY_MEAN_MOTION_THRESHOLD:
        failures.append("mean_motion_below_threshold")
    if float(result.get("sustained_motion_ratio") or 0) < HIGH_QUALITY_SUSTAINED_MOTION_RATIO_THRESHOLD:
        failures.append("sustained_motion_below_threshold")
    if float(result.get("active_ratio") or 0) < HIGH_QUALITY_ACTIVE_RATIO_THRESHOLD:
        failures.append("active_motion_below_threshold")
    if int(result.get("peak_count") or 0) < HIGH_QUALITY_MIN_PEAKS:
        failures.append("motion_peaks_below_threshold")
    return failures


def _probe_loudness(candidate: Path) -> dict[str, float]:
    process = subprocess.run(
        [
            "ffmpeg", "-v", "info", "-i", str(candidate),
            "-af", "loudnorm=I=-16:TP=-1:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    match = re.search(r"\{\s*\"input_i\".*?\}", process.stderr or "", re.DOTALL)
    if process.returncode or not match:
        raise RuntimeError("ffmpeg loudness probe failed")
    measured = json.loads(match.group(0))
    return {
        "integrated_lufs": float(measured["input_i"]),
        "true_peak_dbtp": float(measured["input_tp"]),
    }


def _audio_evidence_check(
    candidate: Path, render_manifest: Mapping[str, object]
) -> dict[str, object]:
    evidence = render_manifest.get("audio_evidence")
    if not isinstance(evidence, dict):
        return {"failures": ["audio_evidence_missing"]}
    failures: list[str] = []
    candidate_digest = _sha256(candidate)
    if evidence.get("candidate_sha256") != candidate_digest:
        failures.append("audio_candidate_hash_mismatch")

    route = str(evidence.get("route") or "")
    required_roles = {
        "embedded_licensed_bgm": {"voiceover", "background_music"},
        "sfx_only": {"voiceover", "sound_effects"},
        "preserve_source_audio": {"source_audio"},
        "platform_native_track": {"voiceover"},
    }.get(route)
    if required_roles is None:
        failures.append("audio_route_missing_or_invalid")
        required_roles = set()

    duration = float(probe_video(candidate).get("duration_seconds") or 0)
    stems = evidence.get("stems")
    observed_roles: set[str] = set()
    if not isinstance(stems, list) or not stems:
        failures.append("audio_stems_missing")
        stems = []
    for stem in stems:
        if not isinstance(stem, dict):
            failures.append("audio_stem_invalid")
            continue
        role = str(stem.get("role") or "")
        observed_roles.add(role)
        path = Path(str(stem.get("path") or ""))
        if not path.is_file():
            failures.append(f"stem_missing:{role or 'unknown'}")
        elif stem.get("sha256") != _sha256(path):
            failures.append(f"stem_hash_mismatch:{role or 'unknown'}")
        declared_coverage = float(stem.get("coverage_ratio") or 0)
        if path.is_file() and duration > 0:
            actual_coverage = min(
                1.0,
                float(probe_video(path).get("duration_seconds") or 0) / duration,
            )
            if actual_coverage < 0.95:
                failures.append(f"stem_coverage_incomplete:{role or 'unknown'}")
            if abs(declared_coverage - actual_coverage) > 0.02:
                failures.append(f"stem_coverage_mismatch:{role or 'unknown'}")
        elif declared_coverage < 0.95:
            failures.append(f"stem_coverage_incomplete:{role or 'unknown'}")
    for role in sorted(required_roles - observed_roles):
        failures.append(f"required_stem_missing:{role}")
    if float(evidence.get("coverage_ratio") or 0) < 0.95:
        failures.append("audio_coverage_incomplete")

    windows = evidence.get("windows")
    if not isinstance(windows, dict):
        windows = {}
    for name in ("opening", "middle", "ending"):
        window = windows.get(name)
        if not isinstance(window, dict):
            failures.append(f"audio_window_missing:{name}")
            continue
        start = float(window.get("start_seconds") or 0)
        end = float(window.get("end_seconds") or 0)
        roles = {str(item) for item in (window.get("stem_roles") or [])}
        if end <= start or float(window.get("coverage_ratio") or 0) < 0.95:
            failures.append(f"audio_window_incomplete:{name}")
        if not required_roles.issubset(roles):
            failures.append(f"audio_window_stems_incomplete:{name}")
        if name == "opening" and start > duration * 0.2:
            failures.append("audio_window_position_invalid:opening")
        elif name == "middle" and not (start <= duration / 2 <= end):
            failures.append("audio_window_position_invalid:middle")
        elif name == "ending" and end < duration * 0.8:
            failures.append("audio_window_position_invalid:ending")

    loudness = evidence.get("final_loudness")
    if not isinstance(loudness, dict) or not all(
        isinstance(loudness.get(field), (int, float))
        for field in ("integrated_lufs", "true_peak_dbtp")
    ):
        failures.append("final_loudness_evidence_missing")
        measured = {}
    else:
        measured = _probe_loudness(candidate)
        for field in ("integrated_lufs", "true_peak_dbtp"):
            if abs(float(loudness[field]) - float(measured[field])) > 0.2:
                failures.append(f"final_loudness_mismatch:{field}")
        if float(measured["true_peak_dbtp"]) > -1.0:
            failures.append("true_peak_above_minus_one_dbtp")
    return {
        "route": route,
        "candidate_sha256": candidate_digest,
        "measured_loudness": measured,
        "failures": failures,
    }


def _dedup_check(
    candidate: Path, *, evidence_path: Path, required: bool
) -> dict[str, object]:
    """Validate repost dedup evidence against the exact release candidate."""
    candidate_digest = _sha256(candidate)
    if not required:
        return {
            "required": False,
            "final_mp4_sha256": candidate_digest,
            "failures": [],
        }

    failures: list[str] = []
    try:
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        evidence = {}
        failures.append("dedup_evidence_missing_or_invalid")
    if not isinstance(evidence, dict):
        evidence = {}
        failures.append("dedup_evidence_not_object")

    fingerprints = evidence.get("fingerprints")
    history = evidence.get("history_index")
    transform = evidence.get("transform")
    rights = evidence.get("rights")
    post_render = evidence.get("post_render_verification")
    if evidence.get("passed") is not True:
        failures.append("dedup_not_passed")
    if evidence.get("stage") != "post_render":
        failures.append("dedup_not_post_render")
    if evidence.get("final_mp4_sha256") != candidate_digest:
        failures.append("final_mp4_sha256_mismatch")
    if not isinstance(fingerprints, dict) or not (
        fingerprints.get("sha256") == candidate_digest
        and fingerprints.get("frame_phashes")
        and fingerprints.get("audio_fingerprint")
    ):
        failures.append("fingerprints_incomplete_or_mismatched")
    if not isinstance(history, dict) or not (
        history.get("status") == "available"
        and isinstance(history.get("path"), str)
        and bool(history.get("path"))
        and isinstance(history.get("entry_count"), int)
        and not isinstance(history.get("entry_count"), bool)
        and history.get("entry_count", -1) >= 0
    ):
        failures.append("history_incomplete")
    if not isinstance(transform, dict) or not (
        transform.get("kind") and transform.get("description")
    ):
        failures.append("transform_incomplete")
    if not isinstance(rights, dict) or not (
        rights.get("basis") and rights.get("reference")
    ):
        failures.append("rights_incomplete")
    if not isinstance(post_render, dict) or not (
        post_render.get("required") is True and post_render.get("passed") is True
    ):
        failures.append("post_render_verification_incomplete")
    return {
        "required": True,
        "final_mp4_sha256": candidate_digest,
        "evidence_path": str(Path(evidence_path).resolve()),
        "evidence_sha256": _sha256(Path(evidence_path)) if Path(evidence_path).is_file() else "",
        "failures": failures,
    }


def _package_check(
    manifest: RunManifest,
    *,
    preview: Path,
    evidence_paths: Mapping[str, Path],
) -> dict[str, object]:
    failures: list[str] = []
    for artifact in manifest.spec.artifacts:
        if not artifact.path.is_file():
            failures.append(f"artifact_missing:{artifact.name}")
            continue
        expected = manifest.artifact_sha256.get(artifact.name)
        if expected != _sha256(artifact.path):
            failures.append(f"artifact_hash_mismatch:{artifact.name}")
    if not preview.is_file():
        failures.append("preview_missing")
    for checker, path in evidence_paths.items():
        if not path.is_file():
            failures.append(f"checker_evidence_missing:{checker}")
            continue
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
            declared = str(evidence.pop("evidence_sha256", ""))
            actual = hashlib.sha256(
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if declared != actual:
                failures.append(f"checker_evidence_hash_mismatch:{checker}")
            if evidence.get("verdict") != "pass":
                failures.append(f"checker_not_passed:{checker}")
        except (OSError, ValueError, json.JSONDecodeError):
            failures.append(f"checker_evidence_invalid:{checker}")
    return {
        "failures": failures,
        "artifacts": dict(manifest.artifact_sha256),
        "preview_sha256": _sha256(preview) if preview.is_file() else "",
        "evidence_files": {name: str(path) for name, path in evidence_paths.items()},
    }


def _release_rendered_candidate(
    manifest: RunManifest,
    *,
    output_dir: Path,
    candidate: Path,
    cover: Path,
    cover_evidence: Path,
    platform: str,
    render_manifest: Mapping[str, object],
    trusted_manifest_path: Path,
) -> RunManifest:
    """Run real checkers and atomically promote one rendered candidate."""
    if manifest.state is not RunState.ASSETS_VALIDATED:
        raise ValueError(f"release runtime requires ASSETS_VALIDATED, got {manifest.state.value}")
    output_dir = Path(output_dir).resolve()
    candidate = Path(candidate).resolve()
    cover = Path(cover).resolve()
    preview = output_dir / "preview.mp4"
    preview_payload = create_preview(candidate, preview)
    _write_evidence(output_dir / "preview_evidence.json", preview_payload)
    current = manifest.advance(RunState.PREVIEW_VALIDATED)
    current = current.advance(RunState.RENDERING)
    current = current.bind_outputs().advance(RunState.RENDERED_UNVERIFIED)
    write_manifest_atomic(current, trusted_manifest_path)

    from scripts.cover_quality_gate import validate_cover
    from scripts.film_renderer import probe_audio_spec, validate_audio_spec

    media_result = verify_artifact(candidate, dict(render_manifest), platform)
    pixel_result = verify_final_pixels(candidate)
    media_result = {
        **media_result,
        "final_pixel_gate": pixel_result,
    }
    media_failures = [str(item) for item in media_result.get("failed_dimensions") or []]
    if pixel_result.get("passed") is not True:
        media_failures.extend(f"final_pixel:{item}" for item in pixel_result.get("failures") or ["failed"])
    visual_result = measure_motion_evidence(candidate)
    visual_failures = _visual_failures(
        visual_result,
        candidate_sha256=_sha256(candidate),
        render_manifest=render_manifest,
    )
    audio_spec_result = validate_audio_spec(probe_audio_spec(candidate))
    audio_evidence_result = _audio_evidence_check(candidate, render_manifest)
    audio_result = {
        "audio_spec": audio_spec_result,
        "audio_evidence": audio_evidence_result,
    }
    audio_failures = [str(item) for item in audio_spec_result.get("failures") or []]
    audio_failures.extend(str(item) for item in audio_evidence_result.get("failures") or [])
    cover_result = validate_cover(cover, Path(cover_evidence))
    cover_failures = [str(item) for item in cover_result.get("failures") or []]
    if str(cover_result.get("status") or "error") != "pass":
        cover_failures.append(f"cover_status_{cover_result.get('status') or 'error'}")
    if cover_result.get("passed") is not True:
        cover_failures.append("cover_passed_false")
    cover_failures = list(dict.fromkeys(cover_failures))
    dedup_result = _dedup_check(
        candidate,
        evidence_path=output_dir / "dedup_evidence.json",
        required=str(render_manifest.get("selected_pipeline") or "")
        == "localized_repost_video",
    )
    dedup_failures = [str(item) for item in dedup_result.get("failures") or []]

    raw_results: dict[str, tuple[Mapping[str, object], list[str]]] = {
        "dedup": (dedup_result, dedup_failures),
        "media": (media_result, media_failures),
        "visual": (visual_result, visual_failures),
        "audio": (audio_result, audio_failures),
        "cover": (cover_result, cover_failures),
    }
    bound: dict[str, Mapping[str, object]] = {}
    evidence_paths: dict[str, Path] = {}
    candidate_sha256 = _sha256(candidate)
    for checker, (result, failures) in raw_results.items():
        path = output_dir / f"{checker}_checker_evidence.json"
        _, digest = _write_evidence(
            path,
            {
                "checker": checker,
                "verdict": "fail" if failures else "pass",
                "failures": failures,
                "artifact": str(candidate if checker != "cover" else cover),
                "artifact_sha256": candidate_sha256 if checker != "cover" else _sha256(cover),
                "result": dict(result),
            },
        )
        evidence_paths[checker] = path
        bound[checker] = bind_checker_result(
            current,
            checker=checker,
            passed=not failures,
            failures=failures,
            evidence_sha256=digest,
        )

    package_result = _package_check(current, preview=preview, evidence_paths=evidence_paths)
    package_failures = [str(item) for item in package_result["failures"]]
    package_path = output_dir / "package_checker_evidence.json"
    _, package_digest = _write_evidence(
        package_path,
        {
            "checker": "package",
            "verdict": "fail" if package_failures else "pass",
            "failures": package_failures,
            "artifact": str(candidate),
            "artifact_sha256": candidate_sha256,
            "result": package_result,
        },
    )
    bound["package"] = bind_checker_result(
        current,
        checker="package",
        passed=not package_failures,
        failures=package_failures,
        evidence_sha256=package_digest,
    )
    bundle_identity = {
        "run_id": current.spec.run_id,
        "revision": current.spec.revision,
        "attempt_id": current.spec.attempt_id,
        "platform": platform,
        "resolved_output_dir": str(output_dir),
    }
    delivery = build_delivery_manifest(
        output_dir,
        required_paths=[candidate, cover, preview, *evidence_paths.values(), package_path],
        identity=bundle_identity,
    )
    (output_dir / "delivery_manifest.json").write_text(json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8")
    runner_path = output_dir / "video_toolchain_runner_manifest.json"
    if not runner_path.is_file():
        runner_path.write_text(json.dumps({"ok": True, "artifact_set_sha256": delivery["artifact_set_sha256"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    released = release_to_handoff(current, bound)
    write_manifest_atomic(released, trusted_manifest_path)
    trusted_payload = json.loads(trusted_manifest_path.read_text(encoding="utf-8"))
    trusted_payload.update({"artifact_set_sha256": delivery["artifact_set_sha256"], "resolved_output_dir": str(output_dir), "delivery_manifest_path": str(output_dir / "delivery_manifest.json")})
    trusted_manifest_path.write_text(json.dumps(trusted_payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return released


def release_rendered_candidate(
    manifest: RunManifest,
    *,
    output_dir: Path,
    candidate: Path,
    cover: Path,
    cover_evidence: Path,
    platform: str,
    render_manifest: Mapping[str, object],
    trusted_manifest_path: Path,
) -> RunManifest:
    """Promote or atomically persist an explicit retryable/terminal failure."""
    try:
        return _release_rendered_candidate(
            manifest,
            output_dir=output_dir,
            candidate=candidate,
            cover=cover,
            cover_evidence=cover_evidence,
            platform=platform,
            render_manifest=render_manifest,
            trusted_manifest_path=trusted_manifest_path,
        )
    except Exception as error:
        target = (
            RunState.BLOCKED_DEDUP
            if isinstance(error, DedupBlocked)
            else (
                RunState.FAILED_TERMINAL
                if isinstance(error, (ReleaseBlocked, ValueError, json.JSONDecodeError))
                else RunState.FAILED_RETRYABLE
            )
        )
        reason = f"{type(error).__name__}: {error}"
        failed = manifest.fail(target, reason=reason)
        write_manifest_atomic(failed, trusted_manifest_path)
        raise
