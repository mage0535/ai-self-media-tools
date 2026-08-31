"""Platform deliverable contracts evaluated against real artifact files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .content_policy import SHORT_VIDEO_PLATFORMS


ARTICLE_MEDIA_PLATFORMS = frozenset(
    {"wechat", "wechat_official", "weixin", "zhihu", "juejin", "xiaohongshu", "rednote"}
)


def required_artifact_kinds(platforms: list[str]) -> set[str]:
    normalized = {str(platform).casefold() for platform in platforms}
    required: set[str] = set()
    if normalized.intersection(SHORT_VIDEO_PLATFORMS):
        required.update({"video", "cover"})
    if normalized.intersection(ARTICLE_MEDIA_PLATFORMS):
        required.update({"image", "cover"})
    return required


def validate_platform_artifacts(job: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    required = required_artifact_kinds(list(job.get("platforms") or []))
    valid: dict[str, list[dict[str, Any]]] = {}
    invalid: list[dict[str, str]] = []
    for artifact in artifacts or []:
        kind = str(artifact.get("kind") or "").casefold()
        path = Path(str(artifact.get("path") or ""))
        if kind and path.is_file() and path.stat().st_size > 0:
            valid.setdefault(kind, []).append(artifact)
        elif kind in required:
            invalid.append({"kind": kind, "path": str(path), "reason": "missing_or_empty"})
    missing = sorted(kind for kind in required if not valid.get(kind))
    return {
        "version": "platform_artifact_contract_v1",
        "passed": not missing and not invalid,
        "platforms": list(job.get("platforms") or []),
        "required_kinds": sorted(required),
        "verified_kinds": sorted(valid),
        "missing_kinds": missing,
        "invalid_artifacts": invalid,
    }
