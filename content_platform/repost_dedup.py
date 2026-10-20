"""Fail-closed duplicate evidence for localized repost videos."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


EVIDENCE_VERSION = "repost_dedup_v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_media_command(command: list[str]) -> bytes:
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace")[-600:]
        raise RuntimeError(message or f"media command failed: {command[0]}")
    return result.stdout


def _video_duration(path: Path) -> float:
    output = _run_media_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    try:
        duration = float(output.decode("ascii").strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe returned no valid video duration") from exc
    if duration <= 0:
        raise RuntimeError("video duration must be positive")
    return duration


def _image_phash(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((32, 32)).tobytes())
    coefficients: list[float] = []
    for vertical in range(8):
        for horizontal in range(8):
            value = 0.0
            for y in range(32):
                vertical_cosine = math.cos((2 * y + 1) * vertical * math.pi / 64)
                row = y * 32
                for x in range(32):
                    value += (
                        pixels[row + x]
                        * math.cos((2 * x + 1) * horizontal * math.pi / 64)
                        * vertical_cosine
                    )
            coefficients.append(value)
    ordered = sorted(coefficients[1:])
    median = ordered[len(ordered) // 2]
    bits = 0
    for coefficient in coefficients:
        bits = (bits << 1) | int(coefficient >= median)
    return f"{bits:016x}"


def fingerprint_video(path: str | Path) -> dict[str, Any]:
    """Return SHA-256, uniformly sampled frame pHashes, and decoded-audio hash."""
    candidate = Path(path)
    if not candidate.is_file():
        raise ValueError(f"video does not exist: {candidate}")
    duration = _video_duration(candidate)
    timestamps = sorted({max(0.0, duration * fraction) for fraction in (0.1, 0.5, 0.9)})
    frame_hashes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repost-phash-") as directory:
        for index, timestamp in enumerate(timestamps):
            frame = Path(directory) / f"frame-{index}.png"
            _run_media_command(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(candidate),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=32:32",
                    "-y",
                    str(frame),
                ]
            )
            if frame.is_file():
                frame_hashes.append(_image_phash(frame))
    audio = _run_media_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(candidate),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ]
    )
    if not audio:
        raise RuntimeError("video has no decodable audio fingerprint")
    return {
        "sha256": _sha256_file(candidate),
        "frame_phashes": frame_hashes,
        "frame_algorithm": "phash_dct_32x32_64bit",
        "frame_sample_count": len(frame_hashes),
        "audio_fingerprint": hashlib.sha256(audio).hexdigest(),
        "audio_algorithm": "pcm_s16le_8khz_mono_sha256",
        "duration_seconds": round(duration, 6),
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_history(path: Path) -> tuple[str, list[dict[str, Any]], str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return "unavailable", [], f"{type(exc).__name__}: {exc}"
    rows: list[dict[str, Any]] = []
    try:
        for line in lines:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("history row must be an object")
                fingerprints = row.get("fingerprints")
                if not isinstance(fingerprints, dict):
                    raise ValueError("history row fingerprints missing")
                rows.append(row)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return "invalid", [], f"{type(exc).__name__}: {exc}"
    return "available", rows, ""


def _phash_similarity(left: str, right: str) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    try:
        distance = (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 0.0
    return 1.0 - distance / (len(left) * 4)


def _compare_history(
    fingerprints: dict[str, Any], rows: list[dict[str, Any]], threshold: float
) -> tuple[float, list[dict[str, Any]]]:
    maximum = 0.0
    matches: list[dict[str, Any]] = []
    candidate_hashes = fingerprints.get("frame_phashes") or []
    for index, row in enumerate(rows):
        historical = row["fingerprints"]
        frame_similarity = max(
            (
                _phash_similarity(str(current), str(previous))
                for current in candidate_hashes
                for previous in (historical.get("frame_phashes") or [])
            ),
            default=0.0,
        )
        maximum = max(maximum, frame_similarity)
        sha_match = bool(
            fingerprints.get("sha256")
            and fingerprints.get("sha256") == historical.get("sha256")
        )
        audio_match = bool(
            fingerprints.get("audio_fingerprint")
            and fingerprints.get("audio_fingerprint")
            == historical.get("audio_fingerprint")
        )
        if sha_match or audio_match or frame_similarity >= threshold:
            matches.append(
                {
                    "history_row": index,
                    "source_identity": row.get("source_identity") or {},
                    "sha256_match": sha_match,
                    "audio_match": audio_match,
                    "frame_similarity": round(frame_similarity, 6),
                }
            )
    return maximum, matches


def build_dedup_evidence(
    candidate_path: str | Path,
    *,
    source_identity: dict[str, Any],
    history_index: str | Path,
    transform: dict[str, Any],
    rights: dict[str, Any],
    output_path: str | Path,
    similarity_threshold: float = 0.9,
    stage: str = "pre_render",
    pre_render_fingerprints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fingerprint a candidate, compare history, and atomically persist evidence."""
    history_path = Path(history_index)
    history_status, rows, history_error = _load_history(history_path)
    try:
        fingerprints = fingerprint_video(candidate_path)
    except Exception as exc:
        fingerprints = {"error": f"{type(exc).__name__}: {exc}"}

    maximum, matches = _compare_history(fingerprints, rows, similarity_threshold)
    failures: list[str] = []
    if history_status != "available":
        failures.append(f"history_index_{history_status}")
    if not source_identity.get("source_id") or not source_identity.get("source_uri"):
        failures.append("source_identity_missing")
    if (
        not fingerprints.get("sha256")
        or not fingerprints.get("frame_phashes")
        or not fingerprints.get("audio_fingerprint")
    ):
        failures.append("fingerprints_missing")
    if not transform.get("kind") or not transform.get("description"):
        failures.append("transform_missing")
    if not rights.get("basis") or not rights.get("reference"):
        failures.append("rights_missing")
    if matches:
        failures.append("historical_similarity_match")

    pre_render = dict(pre_render_fingerprints or {})
    post_render_verification = {
        "required": stage == "post_render",
        "passed": stage != "post_render",
        "source_sha256_match": False,
        "max_source_frame_similarity": 0.0,
    }
    if stage == "post_render":
        source_frames = pre_render.get("frame_phashes") or []
        rendered_frames = fingerprints.get("frame_phashes") or []
        source_similarity = max(
            (
                _phash_similarity(str(rendered), str(source))
                for rendered in rendered_frames
                for source in source_frames
            ),
            default=0.0,
        )
        complete = bool(
            pre_render.get("sha256")
            and source_frames
            and pre_render.get("audio_fingerprint")
            and fingerprints.get("sha256")
            and rendered_frames
            and fingerprints.get("audio_fingerprint")
        )
        post_render_verification = {
            "required": True,
            "passed": complete,
            "source_sha256_match": bool(
                complete and pre_render.get("sha256") == fingerprints.get("sha256")
            ),
            "max_source_frame_similarity": round(source_similarity, 6),
        }
        if not complete:
            failures.append("post_render_source_evidence_missing")

    evidence = {
        "version": EVIDENCE_VERSION,
        "stage": stage,
        "candidate_path": str(Path(candidate_path).resolve()),
        "final_mp4_sha256": (
            str(fingerprints.get("sha256") or "") if stage == "post_render" else ""
        ),
        "passed": not failures,
        "source_identity": dict(source_identity),
        "fingerprints": fingerprints,
        "history_index": {
            "status": history_status,
            "path": str(history_path),
            "entry_count": len(rows),
            "error": history_error,
        },
        "similarity": {
            "threshold": similarity_threshold,
            "max_frame_similarity": round(maximum, 6),
            "matches": matches,
        },
        "transform": dict(transform),
        "rights": dict(rights),
        "pre_render_fingerprints": pre_render,
        "post_render_verification": post_render_verification,
        "failures": failures,
    }
    _write_json_atomic(Path(output_path), evidence)
    return evidence
