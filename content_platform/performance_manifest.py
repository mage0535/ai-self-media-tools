"""Atomic, identity-bound performance evidence for video runs."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


class InvalidPerformanceManifest(ValueError):
    pass


def new_performance_manifest(*, job_id: str, platform_run_id: str, platform: str, attempt_id: str, target_seconds: float = 1800.0) -> dict:
    now = time.time()
    return {
        "version": "performance_manifest_v1",
        "job_id": str(job_id),
        "platform_run_id": str(platform_run_id),
        "platform": str(platform),
        "attempt_id": str(attempt_id),
        "started_at": now,
        "finished_at": None,
        "elapsed_seconds": None,
        "slo": {"target_seconds": float(target_seconds), "status": "unknown"},
        "stages": [],
        "cache": {"hits": 0, "misses": 0, "invalidations": []},
        "final_status": "running",
    }


def add_stage(manifest: dict, name: str, elapsed_seconds: float, *, status: str = "passed", cache: str | None = None) -> None:
    if not str(name).strip() or elapsed_seconds < 0:
        raise InvalidPerformanceManifest("stage name and non-negative elapsed_seconds are required")
    manifest.setdefault("stages", []).append({"name": str(name), "elapsed_seconds": float(elapsed_seconds), "status": str(status)})
    if cache == "hit":
        manifest.setdefault("cache", {}).setdefault("hits", 0)
        manifest["cache"]["hits"] += 1
    elif cache == "miss":
        manifest.setdefault("cache", {}).setdefault("misses", 0)
        manifest["cache"]["misses"] += 1


def finish_manifest(manifest: dict, *, final_status: str) -> dict:
    finished = time.time()
    started = manifest.get("started_at")
    if not isinstance(started, (int, float)) or finished < started:
        raise InvalidPerformanceManifest("started_at is invalid")
    manifest["finished_at"] = finished
    manifest["elapsed_seconds"] = round(finished - started, 6)
    target = float((manifest.get("slo") or {}).get("target_seconds") or 1800.0)
    manifest.setdefault("slo", {})["status"] = "passed" if manifest["elapsed_seconds"] <= target and final_status == "success" else "missed" if manifest["elapsed_seconds"] > target else "blocked"
    manifest["final_status"] = str(final_status)
    return manifest


def validate_performance_manifest(manifest: dict) -> dict:
    required = ("version", "job_id", "platform_run_id", "platform", "attempt_id", "started_at", "finished_at", "elapsed_seconds", "slo", "stages", "cache", "final_status")
    missing = [field for field in required if field not in manifest]
    if missing:
        raise InvalidPerformanceManifest(f"missing performance fields: {','.join(missing)}")
    if manifest["version"] != "performance_manifest_v1" or not all(str(manifest.get(field) or "").strip() for field in ("job_id", "platform_run_id", "platform", "attempt_id")):
        raise InvalidPerformanceManifest("performance identity is invalid")
    if manifest["finished_at"] is None or manifest["elapsed_seconds"] is None:
        raise InvalidPerformanceManifest("unfinished performance manifest cannot be evidence")
    if manifest["slo"].get("status") not in {"passed", "missed", "blocked"}:
        raise InvalidPerformanceManifest("performance SLO status is not final")
    return {"passed": True, "manifest": manifest}


def write_performance_manifest(path: Path, manifest: dict) -> None:
    validate_performance_manifest(manifest)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)