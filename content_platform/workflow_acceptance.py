"""Persisted quality acceptance for real generated content packages."""

from __future__ import annotations

import re
import hashlib
import json
from pathlib import Path
from typing import Any

from .cover_quality import validate_cover
from .asset_ledger import AssetLedger, validate_asset_set
from .content_hygiene import validate_generated_text


LONG_FORM_PLATFORMS = {"wechat", "zhihu", "juejin"}
VIDEO_PLATFORMS = {"kuaishou", "douyin", "douyin_ai", "douyin_pet", "shipinhao", "bilibili", "youtube", "tiktok", "xiaohongshu"}
COVER_PLATFORMS = VIDEO_PLATFORMS | LONG_FORM_PLATFORMS


def evaluate_job_acceptance(store: Any, job_id: str, platform: str, *, artifacts_dir: str | Path = "") -> dict[str, Any]:
    """Evaluate the stored job and persist an evidence-backed acceptance result."""
    job = store.get_job(job_id)
    normalized = str(platform or "").casefold()
    body, body_source = _load_body(store, job)
    artifacts = Path(artifacts_dir) if artifacts_dir else _default_artifacts_dir(store, job_id)
    failures: list[str] = []
    asset_gate: dict[str, Any] = {}
    brief = job.get("brief") or {}
    content_hygiene = validate_generated_text(body)
    if brief.get("automated_workflow") is True and not content_hygiene["passed"]:
        failures.append("content_hygiene_failed")
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
    if (job.get("brief") or {}).get("run_contract") and normalized in COVER_PLATFORMS:
        _check_cover_quality(artifacts, store.artifacts(job_id), normalized, failures)
        asset_gate = _check_asset_quality(artifacts, normalized, job_id, store, failures)
    result = {
        "version": "workflow_acceptance_v1",
        "job_id": str(job_id),
        "platform": normalized,
        "passed": not failures,
        "failures": failures,
        "body_source": body_source,
        "artifacts_dir": str(artifacts),
        "asset_quality_gate": asset_gate,
        "content_hygiene": content_hygiene,
    }
    if result["passed"] and asset_gate.get("passed"):
        payload = json.loads((artifacts / "asset_provenance.json").read_text(encoding="utf-8"))
        records = payload.get("assets") if isinstance(payload, dict) else payload
        validate_asset_set(records or [], normalized, str(job_id), AssetLedger(Path(store.path).parent / "asset_ledger.db"), register=True)
    store.save_workflow_acceptance(job_id, result)
    return result


def _has_valid_selection_evidence(brief: dict[str, Any], matrix: dict[str, Any]) -> bool:
    if bool(matrix.get("real_platform_collection_verified")):
        return True
    if str(brief.get("selection_mode") or "") != "editorial_calendar":
        return False
    evidence = brief.get("editorial_evidence") or {}
    if not isinstance(evidence, dict):
        return False
    planned = evidence.get("planned_for") or evidence.get("planned_date")
    dedupe = evidence.get("dedupe_passed") is True or bool(str(evidence.get("dedupe") or "").strip())
    return bool(
        str(evidence.get("strategy_source") or "").strip()
        and str(evidence.get("calendar_column") or "").strip()
        and str(planned or "").strip()
        and dedupe
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


def _check_cover_quality(directory: Path, artifacts: list[dict[str, Any]], platform: str, failures: list[str]) -> None:
    candidates = [path for pattern in ("cover.png", "cover.jpg", "cover.jpeg", "cover*.png", "cover*.jpg", "cover*.jpeg") for path in directory.glob(pattern)]
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        if str(item.get("kind") or "").casefold() == "cover" or path.stem.casefold().startswith("cover"):
            candidates.append(path)
    cover = next((path for path in candidates if path.is_file()), None)
    if cover is None:
        failures.append("cover_missing")
        return
    evidence = directory / "cover_quality_evidence.json"
    result = validate_cover(cover, evidence, platform)
    if not result.get("passed"):
        failures.append("cover_quality_gate_failed")


def _check_asset_quality(directory: Path, platform: str, job_id: str, store: Any, failures: list[str]) -> dict[str, Any]:
    path = directory / "asset_provenance.json"
    if not path.is_file():
        failures.append("asset_provenance_missing")
        return {"passed": False, "failures": ["asset_provenance_missing"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        failures.append("asset_provenance_invalid")
        return {"passed": False, "failures": ["asset_provenance_invalid"]}
    records = payload.get("assets") if isinstance(payload, dict) else payload
    result = validate_asset_set(records or [], platform, str(job_id), AssetLedger(Path(store.path).parent / "asset_ledger.db"))
    if not result.get("passed"):
        failures.append("asset_quality_gate_failed")
    return result
