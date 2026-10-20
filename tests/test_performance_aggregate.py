import pytest

from content_platform.performance_aggregate import (
    InvalidPerformanceAggregate,
    aggregate_performance_manifests,
)
from content_platform.performance_manifest import finish_manifest, new_performance_manifest


def _sample(run_id, seconds, *, quality=True, status="success"):
    manifest = new_performance_manifest(job_id="job", platform_run_id=run_id, platform="kuaishou", attempt_id="attempt-1")
    manifest["started_at"] -= seconds
    finish_manifest(manifest, final_status=status)
    manifest["elapsed_seconds"] = seconds
    manifest["quality"] = {"preserved": quality}
    return manifest


def test_aggregate_uses_only_successful_quality_preserved_samples():
    result = aggregate_performance_manifests([_sample("a", 600), _sample("b", 1200), _sample("c", 900, quality=False), _sample("d", 700, status="blocked")])
    assert result["sample_count"] == 2
    assert result["excluded_count"] == 2
    assert result["p50_seconds"] == 900.0
    assert result["slo"]["passed"] is True


def test_empty_eligible_samples_do_not_claim_slo_success():
    result = aggregate_performance_manifests([_sample("bad", 100, quality=False)])
    assert result["sample_count"] == 0
    assert result["p50_seconds"] is None
    assert result["slo"] == {"passed": False, "quality_preserved": False}


def test_invalid_target_is_rejected():
    with pytest.raises(InvalidPerformanceAggregate):
        aggregate_performance_manifests([], target_seconds=0)