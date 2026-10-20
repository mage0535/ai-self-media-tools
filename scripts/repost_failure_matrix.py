#!/usr/bin/env python3
"""Run local, non-publishing reliability scenarios for the repost workflow."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.repost_workflow import (  # noqa: E402
    RepostState,
    StageLease,
    StageName,
    validate_handoff_directory,
    validate_similarity_report,
    validate_timeline,
)
from scripts.repost_pipeline_runner import run_fixture  # noqa: E402


def scenario_root(base: Path, name: str) -> Path:
    path = base / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_case(name: str, fn):
    started = time.perf_counter()
    try:
        payload = fn()
        return {"scenario": name, "status": "PASSED", "elapsed_seconds": round(time.perf_counter() - started, 6), **payload}
    except Exception as exc:  # the matrix records failure evidence; it does not hide it
        return {"scenario": name, "status": "FAILED", "elapsed_seconds": round(time.perf_counter() - started, 6), "error_type": type(exc).__name__, "error": str(exc)}


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="repost-failure-matrix-"))
    cases = []

    def cold():
        run_dir = scenario_root(base, "cold_full_run")
        result = run_fixture(run_dir)
        return {"state": result["state"], "handoff_passed": result["handoff_validation"]["passed"], "run_dir": str(run_dir)}

    cases.append(run_case("cold_full_run", cold))

    hot_dir = scenario_root(base, "exact_hot_run")
    run_fixture(hot_dir)
    def hot():
        started = time.perf_counter()
        samples = []
        for index in range(5):
            sample_started = time.perf_counter()
            result = run_fixture(hot_dir, resume=True)
            samples.append({"sample": index + 1, "elapsed_seconds": round(time.perf_counter() - sample_started, 6), "state": result["state"], "handoff_passed": result["handoff_validation"]["passed"]})
        values = sorted(item["elapsed_seconds"] for item in samples)
        p50 = values[len(values) // 2]
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        return {"samples": samples, "sample_count": len(samples), "p50_seconds": p50, "p95_seconds": p95, "total_seconds": round(time.perf_counter() - started, 6), "slo_status": "fixture_only_unproven_production"}
    cases.append(run_case("exact_hot_run", hot))

    def local_reuse(name: str, stage: str):
        run_dir = scenario_root(base, name)
        first = run_fixture(run_dir)
        before = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
        second = run_fixture(run_dir, retry_stage=stage)
        after = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
        render_before = before["stages"][StageName.RENDERING.value]
        render_after = after["stages"][StageName.RENDERING.value]
        return {"state": second["state"], "handoff_passed": second["handoff_validation"]["passed"], "render_cache_hit": render_after["cache_hit"], "render_output_unchanged": render_before["output_sha256"] == render_after["output_sha256"], "run_dir": str(run_dir)}

    cases.append(run_case("cover_only_change", lambda: local_reuse("cover_only_change", StageName.COVER.value)))
    cases.append(run_case("subtitle_only_change", lambda: local_reuse("subtitle_only_change", StageName.SUBTITLES.value)))

    def tamper():
        run_dir = scenario_root(base, "one_byte_tamper")
        run_fixture(run_dir)
        target = run_dir / "final.mp4"
        target.write_bytes(target.read_bytes() + b"x")
        validation = validate_handoff_directory(run_dir)
        return {"passed": validation["passed"], "failures": validation["failures"], "expected_block": not validation["passed"]}
    cases.append(run_case("one_byte_tamper", tamper))

    def stale_lock():
        run_dir = scenario_root(base, "stale_lock_recovery")
        lease = StageLease(run_dir, "rendering", ttl_seconds=1, owner_pid=99999999)
        lease.path.parent.mkdir(parents=True, exist_ok=True)
        lease.path.write_text(json.dumps({"owner_pid": 99999999, "lease_expires_at": time.time() - 10, "fencing_token": "old", "stage": "rendering"}), encoding="utf-8")
        recovered = StageLease(run_dir, "rendering", ttl_seconds=1, owner_pid=os.getpid())
        recovered.acquire(input_key="new", output_dir=run_dir)
        heartbeat = recovered.heartbeat()
        released = recovered.release()
        return {"heartbeat": heartbeat, "released": released, "lock_exists_after": lease.path.exists()}
    cases.append(run_case("stale_lock_recovery", stale_lock))

    def similarity_block():
        report = {"reviewer_decision": "BLOCKED_INTERNAL_SIMILARITY", "source_video_sha256": "a", "candidate_video_sha256": "b", "source_frame_fingerprint": "a", "candidate_frame_fingerprint": "b", "source_audio_fingerprint": "a", "candidate_audio_fingerprint": "b", "source_segment_to_output_segment_mapping": [], "similarity_scores": {"frame": 0.99}, "threshold_version": "v1", "model_version": "v1", "transformation_ledger": {}}
        result = validate_similarity_report(report)
        return {"passed": result["passed"], "failures": result["failures"], "expected_block": not result["passed"]}
    cases.append(run_case("source_similarity_block", similarity_block))

    def timeline_failure():
        timeline = {"intro": {"start": 0, "duration_actual": 0.5}, "main_content": {"start": 0.5, "end": 8}, "outro": {"start_actual": 8, "duration_actual": 2, "minimum_duration": 2}, "last_narration_end": 7, "final_video_duration": 10}
        result = validate_timeline(timeline, 10)
        return {"passed": result["passed"], "failures": result["failures"], "expected_block": not result["passed"]}
    cases.append(run_case("intro_outro_timeline_failure", timeline_failure))

    def timeout_interruption():
        run_dir = scenario_root(base, "timeout_interruption")
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "repost_pipeline_runner.py"), "--run-dir", str(run_dir), "--fixture"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            process.wait(timeout=0.01)
            interrupted = False
        except subprocess.TimeoutExpired:
            interrupted = True
            process.kill()
            process.wait(timeout=10)
        leftovers = []
        probe = subprocess.run(["pgrep", "-af", "ffmpeg|ffprobe|repost_pipeline_runner.py"], capture_output=True, text=True, check=False)
        for line in probe.stdout.splitlines():
            if str(os.getpid()) not in line and "pgrep" not in line:
                leftovers.append(line)
        return {"interrupted": interrupted, "runner_returncode": process.returncode, "orphan_process_lines": leftovers, "no_orphan_process": not leftovers}
    cases.append(run_case("timeout_interruption", timeout_interruption))

    output = {"version": "repost_failure_matrix_v1", "root": str(base), "cases": cases, "production_publish_attempted": False, "slo_status": "fixture_only_unproven_production"}
    out_path = ROOT / "handoff" / "repost_failure_matrix.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "PASSED" for item in cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
