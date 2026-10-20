"""Evidence-backed same-lane viral work breakdown.

This module deliberately separates *observed reference evidence* from
content-generation plans. Missing visual or copy evidence is blocking; the
module never infers a template or motion recipe from a title.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc
REQUIRED_DIMENSIONS = (
    "content_form",
    "copy_or_script",
    "writing_style",
    "content_structure",
    "topic_direction",
    "asset_analysis",
    "theme_template",
    "voiceover",
    "motion_combination",
    "transition_combination",
)
VIDEO_PLATFORMS = {"kuaishou", "douyin", "douyin_ai", "douyin_pet", "tiktok", "youtube", "bilibili", "shipinhao"}


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo else current.replace(tzinfo=UTC)


def _platform_key(platform: str) -> str:
    return str(platform or "").casefold().strip()


def _has_value(value: Any) -> bool:
    if isinstance(value, (list, tuple, dict, str)):
        return bool(value)
    return value is not None


def _sample_failures(platform: str, sample: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for dimension in REQUIRED_DIMENSIONS:
        if not _has_value(sample.get(dimension)):
            failures.append(f"{dimension}_missing")

    motion = sample.get("motion_combination") or {}
    transition = sample.get("transition_combination") or {}
    voiceover = sample.get("voiceover") or {}
    if not isinstance(motion, dict):
        failures.append("motion_combination_invalid")
    elif _platform_key(platform) in VIDEO_PLATFORMS:
        if motion.get("status") != "verified":
            failures.append("motion_evidence_not_verified")
    elif motion.get("status") != "not_applicable":
        failures.append("motion_applicability_not_declared")

    if not isinstance(transition, dict):
        failures.append("transition_combination_invalid")
    elif _platform_key(platform) in VIDEO_PLATFORMS:
        if transition.get("status") != "verified":
            failures.append("transition_evidence_not_verified")
    elif transition.get("status") != "not_applicable":
        failures.append("transition_applicability_not_declared")

    if not isinstance(voiceover, dict):
        failures.append("voiceover_invalid")
    elif _platform_key(platform) in VIDEO_PLATFORMS:
        if voiceover.get("status") != "verified":
            failures.append("voiceover_evidence_not_verified")
    elif voiceover.get("status") != "not_applicable":
        failures.append("voiceover_applicability_not_declared")

    visual_evidence = sample.get("visual_evidence") or []
    if _platform_key(platform) in VIDEO_PLATFORMS and not visual_evidence:
        failures.append("visual_evidence_missing")

    assets = sample.get("asset_analysis") or {}
    if isinstance(assets, dict) and assets.get("count", 1) == 0:
        failures.append("asset_evidence_empty")
    return list(dict.fromkeys(failures))


def validate_breakdown_report(report: dict[str, Any]) -> dict[str, Any]:
    failures = list(report.get("failures") or [])
    if not report.get("platform"):
        failures.append("platform_missing")
    if not report.get("samples"):
        failures.append("samples_missing")
    if report.get("cache", {}).get("ttl_days", 0) <= 0:
        failures.append("cache_ttl_missing")
    passed = not failures and report.get("status") == "ready"
    return {"passed": passed, "failures": list(dict.fromkeys(failures))}


def build_breakdown_report(
    platform: str,
    samples: list[dict[str, Any]],
    *,
    collected_at: datetime | None = None,
    ttl_days: int = 7,
) -> dict[str, Any]:
    """Build a cacheable report from observed same-lane work samples.

    The caller must provide evidence fields on each sample. This function is
    intentionally conservative: it records missing dimensions instead of
    manufacturing analysis from titles or manifests.
    """
    generated = _now(collected_at)
    normalized: list[dict[str, Any]] = []
    failures: list[str] = []
    for raw in samples:
        sample = dict(raw)
        sample_failures = _sample_failures(platform, sample)
        if sample_failures:
            sample["breakdown_failures"] = sample_failures
            failures.extend(sample_failures)
        normalized.append(sample)

    accepted = len(normalized) > 0 and not failures
    expires_at = generated + timedelta(days=max(1, int(ttl_days)))
    report = {
        "version": "viral_breakdown_v2",
        "status": "ready" if accepted else "blocked",
        "platform": _platform_key(platform),
        "generated_at": generated.isoformat(),
        "required_dimensions": list(REQUIRED_DIMENSIONS),
        "samples": normalized,
        "summary": {
            "sample_count": len(normalized),
            "accepted_samples": len(normalized) if accepted else 0,
            "rejected_samples": len(normalized) - (len(normalized) if accepted else 0),
        },
        "failures": list(dict.fromkeys(failures)),
        "cache": {
            "ttl_days": max(1, int(ttl_days)),
            "expires_at": expires_at.isoformat(),
            "reuse_policy": "reuse_until_expiry_then_refresh_or_block",
        },
    }
    report["validation"] = validate_breakdown_report(report)
    return report


def cache_is_fresh(report: dict[str, Any], now: datetime | None = None) -> bool:
    cache = report.get("cache") or {}
    expires = str(cache.get("expires_at") or "")
    if not expires:
        return False
    try:
        expiry = datetime.fromisoformat(expires)
    except ValueError:
        return False
    current = _now(now)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return report.get("status") == "ready" and current < expiry
