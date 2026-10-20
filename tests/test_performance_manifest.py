from __future__ import annotations

import pytest


def test_unfinished_performance_manifest_cannot_be_evidence(tmp_path):
    from content_platform.performance_manifest import (
        InvalidPerformanceManifest,
        new_performance_manifest,
        write_performance_manifest,
    )

    manifest = new_performance_manifest(job_id="job-1", platform_run_id="prun-1", platform="kuaishou", attempt_id="attempt-1")
    with pytest.raises(InvalidPerformanceManifest, match="unfinished"):
        write_performance_manifest(tmp_path / "performance_manifest.json", manifest)


def test_performance_manifest_records_stages_cache_and_slo(tmp_path):
    from content_platform.performance_manifest import (
        add_stage,
        finish_manifest,
        new_performance_manifest,
        validate_performance_manifest,
        write_performance_manifest,
    )

    manifest = new_performance_manifest(job_id="job-1", platform_run_id="prun-1", platform="kuaishou", attempt_id="attempt-1")
    add_stage(manifest, "scene", 1.25, cache="hit")
    add_stage(manifest, "final", 2.5, cache="miss")
    finish_manifest(manifest, final_status="success")
    write_performance_manifest(tmp_path / "performance_manifest.json", manifest)
    result = validate_performance_manifest(manifest)
    assert result["passed"] is True
    assert manifest["cache"] == {"hits": 1, "misses": 1, "invalidations": []}
    assert manifest["slo"]["status"] == "passed"