"""Cross-platform performance aggregation with quality-preserving filtering."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .performance_manifest import validate_performance_manifest


class InvalidPerformanceAggregate(ValueError):
    pass


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise InvalidPerformanceAggregate("at least one eligible performance sample is required")
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = rank - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 6)


def aggregate_performance_manifests(manifests: list[dict], *, target_seconds: float = 1800.0) -> dict:
    if target_seconds <= 0:
        raise InvalidPerformanceAggregate("target_seconds must be positive")
    eligible = []
    excluded = []
    for manifest in manifests:
        try:
            validate_performance_manifest(manifest)
            quality = manifest.get("quality", {})
            if manifest.get("final_status") != "success" or quality.get("preserved") is not True:
                excluded.append({"platform_run_id": manifest.get("platform_run_id", ""), "reason": "quality_or_status_not_eligible"})
                continue
            eligible.append(manifest)
        except Exception as exc:
            excluded.append({"platform_run_id": manifest.get("platform_run_id", ""), "reason": str(exc)})
    durations = [float(item["elapsed_seconds"]) for item in eligible]
    return {
        "version": "performance_aggregate_v1",
        "sample_count": len(eligible),
        "excluded_count": len(excluded),
        "excluded": excluded,
        "eligible_platforms": sorted({str(item["platform"]) for item in eligible}),
        "p50_seconds": _percentile(durations, 0.50) if durations else None,
        "p80_seconds": _percentile(durations, 0.80) if durations else None,
        "target_seconds": float(target_seconds),
        "slo": {
            "passed": bool(durations) and all(value <= target_seconds for value in durations),
            "quality_preserved": bool(durations),
        },
    }


def load_and_aggregate_performance(directory: Path, *, target_seconds: float = 1800.0) -> dict:
    manifests = []
    for path in sorted(Path(directory).rglob("performance_manifest.json")):
        try:
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            manifests.append({"platform_run_id": str(path), "final_status": "invalid"})
    return aggregate_performance_manifests(manifests, target_seconds=target_seconds)