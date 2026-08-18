"""Persisted quality acceptance for real generated content packages."""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from .cover_quality import validate_cover
from .asset_ledger import AssetLedger, validate_asset_set


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
    matrix = (job.get("brief") or {}).get("platform_source_matrix") or {}
    if not bool(matrix.get("real_platform_collection_verified")):
        failures.append("platform_evidence_missing")
    gate = (job.get("draft_meta") or {}).get("quality_gate") or {}
    if gate and not bool(gate.get("passed", True)):
        failures.append("content_quality_gate_failed")
    if normalized in LONG_FORM_PLATFORMS:
        _check_long_form(body, failures)
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
    }
    if result["passed"] and asset_gate.get("passed"):
        payload = json.loads((artifacts / "asset_provenance.json").read_text(encoding="utf-8"))
        records = payload.get("assets") if isinstance(payload, dict) else payload
        validate_asset_set(records or [], normalized, str(job_id), AssetLedger(Path(store.path).parent / "asset_ledger.db"), register=True)
    store.save_workflow_acceptance(job_id, result)
    return result


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
    if len([char for char in body if "\u4e00" <= char <= "\u9fff"]) < 2000:
        failures.append("long_form_too_short")
    if len(re.findall(r"^#{1,3}\s", body, re.M)) < 3:
        failures.append("long_form_headings_missing")
    if not re.search(r"(^|\n)[-*•]\s|\n\d+[.、]", body):
        failures.append("long_form_list_missing")
    if not re.search(r"\|.+\|.+\|", body):
        failures.append("long_form_table_missing")
    if not re.search(r"评论|关注|收藏|转发|回复|点赞", body):
        failures.append("long_form_cta_missing")
    if not re.search(r"[>\"「『]", body):
        failures.append("long_form_evidence_missing")


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
