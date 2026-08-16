"""Persisted quality acceptance for real generated content packages."""

from __future__ import annotations

import re
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
