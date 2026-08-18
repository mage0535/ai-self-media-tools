"""Persisted quality acceptance for real generated content packages."""

from __future__ import annotations

import re
import hashlib
from pathlib import Path
from typing import Any


LONG_FORM_PLATFORMS = {"wechat", "zhihu", "juejin"}
VIDEO_PLATFORMS = {"kuaishou", "douyin", "douyin_ai", "douyin_pet", "shipinhao", "bilibili", "youtube", "tiktok", "xiaohongshu"}


def evaluate_job_acceptance(store: Any, job_id: str, platform: str, *, artifacts_dir: str | Path = "") -> dict[str, Any]:
    """Evaluate the stored job and persist an evidence-backed acceptance result."""
    job = store.get_job(job_id)
    normalized = str(platform or "").casefold()
    body, body_source = _load_body(store, job)
    artifacts = Path(artifacts_dir) if artifacts_dir else _default_artifacts_dir(store, job_id)
    failures: list[str] = []
    brief = job.get("brief") or {}
    matrix = brief.get("platform_source_matrix") or {}
    if not _has_valid_selection_evidence(brief, matrix):
        failures.append("platform_evidence_missing")
    gate = (job.get("draft_meta") or {}).get("quality_gate") or {}
    if gate and not bool(gate.get("passed", True)):
        failures.append("content_quality_gate_failed")
    compliance = (job.get("risk") or {}).get("compliance") or {}
    finding_codes = {
        str(item.get("code") or "")
        for item in compliance.get("findings", [])
        if isinstance(item, dict)
    }
    if finding_codes & {"numeric_claim_without_source", "attribution_without_source"}:
        failures.append("unsupported_factual_claims")
    if normalized in LONG_FORM_PLATFORMS:
        _check_long_form(body, failures)
        _check_unverified_first_person_claims(body, brief, failures)
    if normalized in VIDEO_PLATFORMS:
        _check_video_artifacts(artifacts, store.artifacts(job_id), failures)
    result = {
        "version": "workflow_acceptance_v1",
        "job_id": str(job_id),
        "platform": normalized,
        "passed": not failures,
        "failures": failures,
        "body_source": body_source,
        "artifacts_dir": str(artifacts),
    }
    store.save_workflow_acceptance(job_id, result)
    return result


def _has_valid_selection_evidence(brief: dict[str, Any], matrix: dict[str, Any]) -> bool:
    if bool(matrix.get("real_platform_collection_verified")):
        return True
    if str(brief.get("selection_mode") or "") != "editorial_calendar":
        return False
    evidence = brief.get("editorial_evidence") or {}
    return isinstance(evidence, dict) and all(
        str(evidence.get(field) or "").strip()
        for field in ("strategy_source", "calendar_column", "planned_date", "dedupe")
    )


def _check_unverified_first_person_claims(body: str, brief: dict[str, Any], failures: list[str]) -> None:
    if brief.get("verified_first_person_evidence"):
        return
    # Reject fabricated operational authority such as duration, zero-incident,
    # or quantified outage claims. Generic first-person editorial voice is fine.
    patterns = (
        r"我(?:维护|运行|搭建|负责)[^。！？\n]{0,40}(?:\d+\s*(?:个月|年|天)|零事故|\d+\s*小时)",
        r"(?:至今|已经)跑了\s*\d+\s*(?:个月|年|天)",
        r"(?:零事故|从未中断|停摆了\s*\d+\s*小时)",
    )
    if any(re.search(pattern, body) for pattern in patterns):
        failures.append("unverified_first_person_operational_claim")


def _load_body(store: Any, job: dict[str, Any]) -> tuple[str, str]:
    body = str(job.get("body") or "").strip()
    if body:
        return body, "job.body"
    versions = store.draft_versions(job["id"])
    if versions:
        return str(versions[-1].get("body") or "").strip(), "draft_versions.body"
    return "", "missing"


def _default_artifacts_dir(store: Any, job_id: str) -> Path:
    # The state database can be deliberately isolated from the configured
    # runtime data directory during canaries. Prefer a registered media
    # artifact over inferring a sibling directory from the database path.
    for artifact in store.artifacts(job_id):
        path = Path(str(artifact.get("path") or ""))
        if path.suffix.casefold() == ".mp4" and path.is_file():
            return path.parent
    return Path(store.path).parent / "artifacts" / str(job_id)


def _check_long_form(body: str, failures: list[str]) -> None:
    # Only enforce minimum character count; structural checks are advisory
    if len([char for char in body if "\u4e00" <= char <= "\u9fff"]) < 800:
        failures.append("long_form_too_short")


def _check_video_artifacts(directory: Path, artifacts: list[dict[str, Any]], failures: list[str]) -> None:
    paths = [Path(str(item.get("path") or "")) for item in artifacts if isinstance(item, dict)]
    video_exists = (directory / "final.mp4").is_file() or any(path.is_file() and path.suffix.casefold() == ".mp4" for path in paths)
    cover_exists = (directory / "cover.png").is_file() or any(
        path.is_file() and (str(item.get("kind") or "").casefold() == "cover" or path.stem.casefold().startswith("cover"))
        for item, path in zip(artifacts, paths)
    )
    if not video_exists:
        failures.append("video_missing")
    if not (directory / "scene_manifest.json").is_file():
        failures.append("scene_manifest_missing")
    if not (directory / "tts_config.json").is_file():
        failures.append("tts_config_missing")
    if not cover_exists:
        failures.append("cover_missing")
    image_paths = [
        path for item, path in zip(artifacts, paths)
        if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
        and str(item.get("kind") or "").casefold() in {"image", "illustration", "visual", "background"}
    ]
    if len(image_paths) >= 4:
        hashes = [_file_sha256(path) for path in image_paths]
        if len(set(hashes)) < 4:
            failures.append("duplicate_visual_assets")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
