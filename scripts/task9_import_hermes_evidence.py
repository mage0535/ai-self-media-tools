"""Import only independently verifiable Hermes platform evidence into Task9."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.task9_canary import _hotspot_source_hash, build_canary_matrix
from scripts.task9_prepare_inputs import _fit


PLATFORM_DOMAINS = {
    "twitter": {"x.com", "twitter.com"},
    "douyin_ai": {"douyin.com", "www.douyin.com"},
    "douyin_pet": {"douyin.com", "www.douyin.com"},
    "bilibili": {"bilibili.com", "www.bilibili.com", "search.bilibili.com"},
}
NATIVE_TYPES = {"native_search", "native_search + hot_list_api", "hot_search_api", "native"}


def import_evidence(report_path: Path, artifact_root: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cases = {case["platform"]: case for case in build_canary_matrix()}
    source_root = report_path.parent
    output_root = artifact_root / "_inputs" / "hotspots"
    output_root.mkdir(parents=True, exist_ok=True)
    accepted = []
    rejected = []
    for platform, row in (report.get("platforms") or {}).items():
        failures = []
        case = cases.get(platform)
        if not case:
            failures.append("platform_not_in_canary_matrix")
        evidence_type = str(row.get("evidence_type") or "").casefold()
        source_url = str(row.get("source_url") or "")
        host = urlparse(source_url).hostname or ""
        if row.get("native_verified") is not True or evidence_type not in NATIVE_TYPES:
            failures.append("native_verification_missing")
        if host not in PLATFORM_DOMAINS.get(platform, set()):
            failures.append("platform_domain_mismatch")
        title = str(row.get("observed_title") or "")
        score = _fit(title, platform)
        if score < 0.55:
            failures.append("lane_fit_unverified")
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        if platform == "douyin_ai" and int(metrics.get("ai_related") or 0) <= 0:
            failures.append("no_ai_candidate_observed")
        snapshot_value = str(row.get("snapshot_path") or "")
        raw_snapshot = source_root / platform / "evidence_raw.json"
        source_snapshot = raw_snapshot if raw_snapshot.is_file() else (
            source_root / snapshot_value.replace("hermes-recapture/", "") if snapshot_value else raw_snapshot
        )
        if not source_snapshot.is_file() or source_snapshot.stat().st_size <= 0:
            failures.append("raw_snapshot_missing")
        if failures:
            rejected.append({"platform": platform, "failures": sorted(set(failures))})
            continue
        snapshot = output_root / f"{platform}.source{source_snapshot.suffix or '.bin'}"
        shutil.copy2(source_snapshot, snapshot)
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        snapshot_rel = f"hotspots/{snapshot.name}"
        record = {
            "platform": platform, "source_url": source_url, "observed_title": title,
            "fetched_at": row.get("captured_at"), "status": 200,
            "snapshot_path": snapshot_rel, "snapshot_sha256": snapshot_hash,
            "evidence_type": "native", "native_verified": True,
            "association_mode": "auto_browser", "lane_fit_score": score,
            "semantic_fit_score": score,
        }
        record["provenance_hash"] = _hotspot_source_hash(
            platform, source_url, title, fetched_at=record["fetched_at"], status=200,
            snapshot_path=snapshot_rel, snapshot_sha256=snapshot_hash,
        )
        (output_root / f"{platform}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        accepted.append({"platform": platform, "source_url": source_url, "evidence_type": "native"})
    return {"schema": "task9_hermes_import_v1", "accepted": accepted, "rejected": rejected, "passed": bool(accepted)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = import_evidence(Path(args.report), Path(args.artifact_root))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
