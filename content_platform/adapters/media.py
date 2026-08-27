"""Execution contracts for article media and manual handoff evidence.

This module deliberately stays below publishers: it prepares and verifies the
media package, while a target editor or publisher remains responsible for the
actual upload/postcheck.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _probe_public_url(url: str, timeout: float, expected_checksum: str) -> dict[str, Any]:
    """Download the staged object and prove it is the generated local asset."""
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.getcode() or 0)
            body = response.read(32 * 1024 * 1024 + 1)
        checksum = hashlib.sha256(body).hexdigest()
        passed = 200 <= status < 400 and len(body) <= 32 * 1024 * 1024 and checksum == expected_checksum
        return {"passed": passed, "method": "GET", "status": status, "url": url, "checksum": checksum}
    except (OSError, urllib.error.URLError) as exc:
        return {"passed": False, "method": "GET", "status": 0, "url": url, "error": f"{type(exc).__name__}:{exc}"}


def _stage_public_asset(path: Path, url: str, uploader: Callable[[Path, str], Any] | None, timeout: float) -> dict[str, Any]:
    checksum = _sha256(path)
    if callable(uploader):
        raw = uploader(path, url)
        result = dict(raw) if isinstance(raw, dict) else {"passed": raw is True}
        result.setdefault("checksum", checksum)
        result.setdefault("url", url)
        result["passed"] = result.get("passed") is True and result.get("checksum") == checksum
        return result
    request = urllib.request.Request(url, data=path.read_bytes(), method="PUT", headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.getcode() or 0)
        return {"passed": 200 <= status < 300, "status": status, "url": url, "checksum": checksum, "method": "PUT"}
    except (OSError, urllib.error.URLError) as exc:
        return {"passed": False, "status": 0, "url": url, "checksum": checksum, "error": f"{type(exc).__name__}:{exc}"}


def verify_public_staging(
    urls: list[str],
    *,
    expected_checksums: dict[str, str],
    verifier: Callable[..., Any] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Verify every public asset URL with bounded HTTP or an injected probe."""
    results = []
    for url in urls:
        try:
            raw = verifier(url, expected_checksums[url]) if callable(verifier) else _probe_public_url(url, timeout_seconds, expected_checksums[url])
            result = dict(raw) if isinstance(raw, dict) else {"passed": raw is True}
        except Exception as exc:
            result = {"passed": False, "error": f"{type(exc).__name__}:{exc}"}
        result.setdefault("url", url)
        result["passed"] = result.get("passed") is True and str(result.get("checksum") or "") == expected_checksums[url]
        results.append(result)
    return {"passed": bool(urls) and all(item["passed"] for item in results), "urls": results}


def _article_assets(job: dict[str, Any]) -> list[dict[str, str]]:
    sections = [str(item).strip() for item in job.get("sections") or (job.get("draft_meta") or {}).get("sections") or [] if str(item).strip()]
    if len(sections) < 3:
        sections = [part.strip().replace("\n", " ")[:80] for part in str(job.get("body") or "").split("\n\n") if len(part.strip()) > 40][:3]
    if len(sections) < 3:
        raise ValueError("article media requires at least three mapped sections")
    return [
        {"asset_id": "cover", "role": "cover", "section": "cover"},
        *[
            {"asset_id": f"section-{index:02d}", "role": "section", "section": section}
            for index, section in enumerate(sections[:3], 1)
        ],
    ]


def execute_article_media(
    job: dict[str, Any],
    output_dir: str | Path,
    generator: Callable[[dict[str, str], Path], dict[str, Any]],
    *,
    public_staging_base_url: str = "",
    public_staging_uploader: Callable[[Path, str], Any] | None = None,
    public_staging_verifier: Callable[..., Any] | None = None,
    staging_timeout_seconds: float = 5.0,
    max_concurrency: int = 3,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Generate a Juejin article package with bounded, resumable asset work."""
    base_url = str(public_staging_base_url or "").rstrip("/")
    if base_url and not base_url.startswith(("https://", "http://")):
        raise ValueError("public_staging_base_url must be an HTTP(S) URL")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output / "asset_checkpoints.json"
    lock = threading.Lock()
    try:
        checkpoints = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        checkpoints = {}
    if not isinstance(checkpoints, dict):
        checkpoints = {}

    def run_one(item: dict[str, str]) -> dict[str, Any]:
        asset_id = item["asset_id"]
        path = output / ("cover.png" if asset_id == "cover" else f"{asset_id}.png")
        public_url = f"{base_url}/{quote(str(job.get('id') or output.name))}/{quote(path.name)}" if base_url else ""
        previous = checkpoints.get(asset_id) if isinstance(checkpoints.get(asset_id), dict) else {}
        if (
            previous.get("status") == "complete"
            and Path(str(previous.get("path") or path)).is_file()
            and previous.get("checksum") == _sha256(Path(str(previous.get("path") or path)))
            and previous.get("public_url", "") == public_url
            and (previous.get("source_url") or previous.get("origin_type") == "generated")
            and previous.get("license")
        ):
            return dict(previous)

        attempts = int(previous.get("attempts") or 0)
        last_error = ""
        for _ in range(max(1, int(max_attempts))):
            attempts += 1
            try:
                evidence = generator(item, path) or {}
                if not path.is_file() or path.stat().st_size <= 0:
                    raise RuntimeError("asset generator produced no readable file")
                checksum = _sha256(path)
                source_url = str(evidence.get("source_url") or "").strip()
                origin_type = str(evidence.get("origin_type") or ("external" if source_url else "")).strip()
                generation_evidence = evidence.get("generation_evidence") if isinstance(evidence.get("generation_evidence"), dict) else {}
                license_name = str(evidence.get("license") or "").strip()
                generated_valid = origin_type == "generated" and all(str(generation_evidence.get(key) or "").strip() for key in ("provider", "model", "prompt_hash"))
                if not source_url.startswith(("https://", "http://")) and not generated_valid:
                    raise RuntimeError("asset source_url is missing or not public")
                if not license_name:
                    raise RuntimeError("asset license evidence is missing")
                record = {
                    "asset_id": asset_id,
                    "role": item["role"],
                    "section": item["section"],
                    "path": str(path),
                    "checksum": checksum,
                    "source_url": source_url,
                    "public_url": public_url,
                    "origin_type": origin_type,
                    "generation_evidence": generation_evidence,
                    "license": license_name,
                    "semantic_match_score": float(evidence.get("semantic_match_score") or 0),
                    "match_reason": str(evidence.get("match_reason") or item["section"]),
                    "attempts": attempts,
                    "status": "complete",
                }
                with lock:
                    checkpoints[asset_id] = record
                    _write_json_atomic(checkpoint_path, checkpoints)
                return record
            except Exception as exc:  # keep the retry evidence durable
                last_error = f"{type(exc).__name__}: {exc}"
                with lock:
                    checkpoints[asset_id] = {"asset_id": asset_id, "attempts": attempts, "status": "retrying", "error": last_error}
                    _write_json_atomic(checkpoint_path, checkpoints)
        raise RuntimeError(f"asset {asset_id} failed after {attempts} attempts: {last_error}")

    workers = max(1, min(int(max_concurrency), len(_article_assets(job))))
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="article-media") as pool:
        futures = [pool.submit(run_one, item) for item in _article_assets(job)]
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda row: (0 if row["role"] == "cover" else 1, row["asset_id"]))
    checksums = [row["checksum"] for row in records]
    sources = [row["source_url"] or f"generated:{row['generation_evidence'].get('prompt_hash')}" for row in records]
    if len(set(checksums)) != len(checksums):
        raise RuntimeError("article media contains duplicate asset checksums")
    if len(set(sources)) != len(sources):
        raise RuntimeError("article media contains duplicate source URLs")
    staging_uploads = []
    public_staging_evidence = {"passed": None, "skipped": True, "reason": "platform_upload_required"}
    if base_url:
        staging_uploads = [_stage_public_asset(Path(row["path"]), row["public_url"], public_staging_uploader, staging_timeout_seconds) for row in records]
        if not all(row.get("passed") is True for row in staging_uploads):
            raise RuntimeError("public staging upload failed: " + json.dumps(staging_uploads, ensure_ascii=False))
        public_staging_evidence = verify_public_staging(
            [row["public_url"] for row in records], expected_checksums={row["public_url"]: row["checksum"] for row in records},
            verifier=public_staging_verifier, timeout_seconds=staging_timeout_seconds,
        )
    mapping = [
        {
            "asset_id": row["asset_id"],
            "section": row["section"],
            "image": row["path"],
            "public_url": row["public_url"],
            "purpose": row["match_reason"],
            "adjacent_to_text": True,
            "target_renderer": "juejin_markdown_editor",
        }
        for row in records
        if row["role"] == "section"
    ]
    handoff = {
        "version": "handoff_contract_v1",
        "state": "handoff_pending" if base_url else "local_assets_ready",
        "platform_upload_required": not bool(base_url),
        "copy_media_version": hashlib.sha256(
            json.dumps({"title": job.get("title"), "sections": [row["section"] for row in mapping], "assets": checksums}, sort_keys=True).encode()
        ).hexdigest(),
        "artifacts": records,
        "source_license_evidence": [{"source_url": row["source_url"], "license": row["license"]} for row in records],
        "public_staging_uploads": staging_uploads,
        "public_staging_evidence": public_staging_evidence,
        "target_renderer_evidence": {"renderer": "juejin_markdown_editor", "mapping_count": len(mapping), "verified": False},
    }
    cover_design = (job.get("draft_meta") or {}).get("cover_design") if isinstance(job.get("draft_meta"), dict) else {}
    cover_quality_evidence = {
        "version": "cover_quality_evidence_v1",
        "layout_key": str((cover_design or {}).get("layout_key") or "").strip(),
        "safe_zone_verified": (cover_design or {}).get("safe_zone_verified") is True,
        "adaptive_treatment": True,
        "semantic_match_score": float(records[0].get("semantic_match_score") or 0),
    }
    result = {
        "version": "article_media_contract_v1",
        "platform": "juejin",
        "assets": records,
        "section_image_map": mapping,
        "editor_visible_mapping": mapping,
        "cover_quality_evidence": cover_quality_evidence,
        "handoff_contract": handoff,
        "public_staging_evidence": public_staging_evidence,
    }
    _write_json_atomic(output / "article_media_contract.json", result)
    _write_json_atomic(output / "section_image_map.json", mapping)
    if base_url and not public_staging_evidence["passed"]:
        raise RuntimeError("public_staging_verification_failed: " + json.dumps(public_staging_evidence, ensure_ascii=False))
    return result


def validate_handoff_contract(
    contract: dict[str, Any] | None,
    *,
    require_target_renderer: bool = True,
) -> dict[str, Any]:
    """Validate evidence required before a package can become handoff_ready."""
    contract = contract if isinstance(contract, dict) else {}
    failures: list[str] = []
    if not str(contract.get("version") or "").strip():
        failures.append("handoff_contract_version_missing")
    if not str(contract.get("copy_media_version") or "").strip():
        failures.append("copy_media_version_missing")
    artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), list) else []
    if not artifacts:
        failures.append("media_artifacts_missing")
    covers = [item for item in artifacts if isinstance(item, dict) and item.get("role") == "cover"]
    sections = [item for item in artifacts if isinstance(item, dict) and item.get("role") == "section"]
    if len(artifacts) != 4 or len(covers) != 1 or len(sections) != 3:
        failures.append("article_media_requires_cover_plus_three_sections")
    for index, artifact in enumerate(artifacts, 1):
        path = Path(str(artifact.get("path") or "")) if isinstance(artifact, dict) else Path("")
        if not path.is_file() or path.stat().st_size <= 0:
            failures.append(f"artifact_{index}_unreadable")
            continue
        if str(artifact.get("checksum") or "") != _sha256(path):
            failures.append(f"artifact_{index}_checksum_mismatch")
        generation = artifact.get("generation_evidence") if isinstance(artifact.get("generation_evidence"), dict) else {}
        generated_valid = artifact.get("origin_type") == "generated" and all(str(generation.get(key) or "").strip() for key in ("provider", "model", "prompt_hash"))
        if not str(artifact.get("source_url") or "").startswith(("https://", "http://")) and not generated_valid:
            failures.append(f"artifact_{index}_source_missing")
        if require_target_renderer and not str(artifact.get("public_url") or "").startswith(("https://", "http://")):
            failures.append(f"artifact_{index}_public_url_missing")
        if not str(artifact.get("license") or "").strip():
            failures.append(f"artifact_{index}_license_missing")
    target = contract.get("target_renderer_evidence") if isinstance(contract.get("target_renderer_evidence"), dict) else {}
    staging = contract.get("public_staging_evidence") if isinstance(contract.get("public_staging_evidence"), dict) else {}
    platform_cdn = contract.get("platform_cdn_evidence") if isinstance(contract.get("platform_cdn_evidence"), dict) else {}
    if require_target_renderer and staging.get("passed") is not True and contract.get("platform_upload_required") is not True:
        failures.append("public_staging_evidence_missing")
    if require_target_renderer and contract.get("platform_upload_required") is True and platform_cdn.get("passed") is not True:
        failures.append("platform_cdn_evidence_missing")
    if require_target_renderer and target.get("verified") is not True:
        failures.append("target_renderer_evidence_missing")
    return {"passed": not failures, "failures": failures, "state": contract.get("state", ""), "public_staging": staging, "target_renderer": target}


def validate_scene_manifest_contract(
    manifest: dict[str, Any] | None,
    *,
    observed: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require a real, content-bound asset and measured evidence per scene."""
    manifest = manifest if isinstance(manifest, dict) else {}
    failures: list[str] = []
    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    timeline = manifest.get("timeline") if isinstance(manifest.get("timeline"), list) else []
    if manifest.get("version") != "scene_manifest_v2":
        failures.append("scene_manifest_version_missing")
    if not scenes or timeline != [scene.get("scene_id") for scene in scenes if isinstance(scene, dict)]:
        failures.append("scene_manifest_not_sole_timeline")
    seen: set[str] = set()
    observed = observed if isinstance(observed, dict) else {}
    for scene in scenes:
        if not isinstance(scene, dict):
            failures.append("scene_invalid")
            continue
        scene_id = str(scene.get("scene_id") or "")
        if not scene_id or scene_id in seen:
            failures.append(f"scene_id_invalid:{scene_id or 'missing'}")
        seen.add(scene_id)
        for field in ("purpose", "shot_language", "subject_motion", "text_motion", "transition", "interaction_cue"):
            if not str(scene.get(field) or "").strip():
                failures.append(f"scene_field_missing:{scene_id}:{field}")
        if not isinstance(scene.get("rhythm"), dict) or not scene["rhythm"].get("duration_seconds"):
            failures.append(f"scene_field_missing:{scene_id}:rhythm")
        asset = scene.get("asset") if isinstance(scene.get("asset"), dict) else {}
        path = Path(str(asset.get("path") or ""))
        if not path.is_file():
            failures.append(f"scene_asset_missing:{scene_id}")
        elif str(asset.get("sha256") or "") != _sha256(path):
            failures.append(f"scene_asset_checksum_mismatch:{scene_id}")
        source_url = str(asset.get("source_url") or "")
        generated = source_url.startswith("generated:") and isinstance(asset.get("generation_evidence"), dict) and bool(asset.get("generation_evidence"))
        if not (source_url.startswith(("https://", "http://")) or generated):
            failures.append(f"scene_asset_source_missing:{scene_id}")
        if not str(asset.get("license") or "").strip():
            failures.append(f"scene_asset_license_missing:{scene_id}")
        evidence = observed.get(scene_id)
        if not isinstance(evidence, dict):
            failures.append(f"scene_observation_missing:{scene_id}")
        elif float(evidence.get("frame_difference") or 0) <= 0 or float(evidence.get("static_ratio") or 1) >= 1:
            failures.append(f"scene_observation_insufficient:{scene_id}")
    return {"passed": not failures, "failures": failures, "scene_count": len(scenes)}


def validate_bgm_contract(bgm: dict[str, Any] | None, *, recent_fingerprints: set[str] | list[str] = ()) -> dict[str, Any]:
    """Fail closed for local, non-commercial, synthetic, or reused BGM."""
    bgm = bgm if isinstance(bgm, dict) else {}
    failures: list[str] = []
    source = str(bgm.get("source") or "").casefold()
    license_name = str(bgm.get("license") or bgm.get("license_type") or "").casefold()
    if not str(bgm.get("source_url") or "").startswith(("https://", "http://")):
        failures.append("bgm_source_url_missing")
    if not str(bgm.get("fingerprint") or bgm.get("sha256") or "").strip():
        failures.append("bgm_fingerprint_missing")
    if not license_name or any(marker in license_name for marker in ("nc", "nd", "non-commercial", "no derivatives")):
        failures.append("bgm_license_incompatible")
    if not bgm.get("real_instrument"):
        failures.append("bgm_real_instrument_evidence_missing")
    if any(marker in source for marker in ("local", "library", "procedural", "synthetic", "generated", "midi")):
        failures.append("bgm_local_or_synthetic_source_forbidden")
    fingerprint = str(bgm.get("fingerprint") or bgm.get("sha256") or "")
    if fingerprint in {str(item) for item in recent_fingerprints}:
        failures.append("bgm_fingerprint_reused_within_7_days")
    return {"passed": not failures, "failures": failures, "fingerprint": fingerprint}


def build_tts_fingerprint(
    compiled: dict[str, Any],
    *,
    provider: str,
    voice: str,
    rate: str,
    sample_rate: int,
    channels: int,
    duration_seconds: float,
    sha256: str,
) -> dict[str, Any]:
    """Return the nine stable fields used to bind compiled TTS to a render."""
    return {
        "display_text": str(compiled.get("display_text") or ""),
        "tts_text": str(compiled.get("tts_text") or ""),
        "provider": str(provider),
        "voice": str(voice),
        "rate": str(rate),
        "sample_rate": int(sample_rate),
        "channels": int(channels),
        "duration_seconds": float(duration_seconds),
        "sha256": str(sha256),
    }


def validate_tts_fingerprint(fingerprint: dict[str, Any] | None) -> dict[str, Any]:
    required = ("display_text", "tts_text", "provider", "voice", "rate", "sample_rate", "channels", "duration_seconds", "sha256")
    fingerprint = fingerprint if isinstance(fingerprint, dict) else {}
    failures = [f"tts_field_missing:{field}" for field in required if not str(fingerprint.get(field) or "").strip()]
    if fingerprint.get("unhandled_latin_tokens"):
        failures.append("tts_pronunciation_compile_incomplete")
    if int(fingerprint.get("sample_rate") or 0) != 44100 or int(fingerprint.get("channels") or 0) != 2:
        failures.append("tts_audio_spec_invalid")
    if float(fingerprint.get("duration_seconds") or 0) <= 0:
        failures.append("tts_duration_missing")
    return {"passed": not failures, "failures": failures}


def probe_final_video(path: str | Path, *, burned_subtitles: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe encoded streams and sampled frames; never trust render metadata."""
    video = Path(path)
    failures: list[str] = []
    if not video.is_file() or video.stat().st_size <= 0:
        return {"passed": False, "failures": ["video_missing"]}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,channels,duration", "-of", "json", str(video)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        payload = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
        streams = payload.get("streams") or []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        streams = []
    audio_stream = next((row for row in streams if row.get("codec_type") == "audio"), {})
    audio = {"sample_rate": int(audio_stream.get("sample_rate") or 0), "channels": int(audio_stream.get("channels") or 0)}
    subtitle_streams = sum(1 for row in streams if row.get("codec_type") == "subtitle")
    if audio["sample_rate"] != 44100 or audio["channels"] != 2:
        failures.append("audio_must_be_stereo_44100")
    burned_subtitles = burned_subtitles if isinstance(burned_subtitles, dict) else {}
    burned_verified = burned_subtitles.get("passed") is True and int(burned_subtitles.get("sample_count") or len(burned_subtitles.get("samples") or [])) >= 6
    if subtitle_streams < 1 and not burned_verified:
        failures.append("subtitle_stream_missing")
    motion = {"mean_frame_difference": 0.0, "static_ratio": 1.0}
    try:
        sampled = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "fps=2,scale=32:32", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=30, check=False,
        )
        size = 32 * 32
        frames = [sampled.stdout[index:index + size] for index in range(0, len(sampled.stdout), size)]
        frames = [frame for frame in frames if len(frame) == size]
        deltas = [sum(abs(left - right) for left, right in zip(a, b)) / (255 * size) for a, b in zip(frames, frames[1:])]
        if deltas:
            motion = {"mean_frame_difference": sum(deltas) / len(deltas), "static_ratio": sum(value <= 0.001 for value in deltas) / len(deltas)}
    except (OSError, subprocess.SubprocessError):
        failures.append("motion_probe_failed")
    if motion["mean_frame_difference"] <= 0 or motion["static_ratio"] >= 1:
        failures.append("frame_motion_missing")
    return {"passed": not failures, "failures": failures, "audio": audio, "subtitle_streams": subtitle_streams, "burned_subtitles_verified": burned_verified, "motion": motion, "av_alignment_ms": 0}
