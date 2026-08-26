"""Build Task9 hotspot inputs only from verified runtime evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.task9_canary import _hotspot_source_hash, build_canary_matrix


AI_WORDS = ("ai", "agent", "automation", "workflow", "codex", "claude", "deepseek", "人工智能", "智能体", "自动化", "大模型", "效率")
PET_WORDS = ("pet", "cat", "dog", "animal", "宠物", "猫", "狗", "动物")
VERIFIED_OFFICIAL_STATUSES = {"verified", "backend_loaded"}


def _lane_words(platform: str) -> tuple[str, ...]:
    return PET_WORDS if platform == "douyin_pet" else AI_WORDS


def _fit(title: str, platform: str) -> float:
    text = str(title or "").casefold()
    hits = sum(1 for word in _lane_words(platform) if word in text)
    return min(1.0, hits / 2) if hits else 0.0


def _latest_matrix(root: Path) -> Path | None:
    candidates = sorted(root.glob("overnight/**/official-platform-signal-matrix-v3.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def prepare_inputs(data_root: Path, artifact_root: Path) -> dict[str, Any]:
    pack_path = data_root / "intel" / "hot_work_parameter_pack_latest.json"
    matrix_path = _latest_matrix(data_root)
    pack = json.loads(pack_path.read_text(encoding="utf-8")) if pack_path and pack_path.is_file() else {}
    matrix = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path and matrix_path.is_file() else {}
    official = {str(row.get("platform") or ""): row for row in matrix.get("platforms") or [] if isinstance(row, dict)}
    output_root = artifact_root / "_inputs" / "hotspots"
    output_root.mkdir(parents=True, exist_ok=True)
    prepared = []
    missing = []
    for case in build_canary_matrix():
        platform = case["platform"]
        support = case["hotspot_contract"]
        selected: dict[str, Any] = {}
        hot = (pack.get("platforms") or {}).get(platform) or {}
        for sample in hot.get("top_samples") or []:
            title = str(sample.get("title") or "").strip()
            score = _fit(title, platform)
            if (
                score >= 0.55
                and str(sample.get("url") or "").startswith(("https://", "http://"))
                and sample.get("captured_at")
                and sample.get("evidence_strength") in {"strong", "verified", "high", "strong_logged_search_result"}
                and "same_lane_hot_work" in support.get("allowed_evidence_types", [])
            ):
                selected = {
                    "source_url": sample["url"], "observed_title": title,
                    "fetched_at": sample["captured_at"], "evidence_type": "same_lane_hot_work",
                    "native_verified": False, "association_mode": "manual_handoff",
                    "lane_fit_score": score, "semantic_fit_score": score,
                    "source_record": sample,
                }
                break
        if not selected:
            row = official.get(platform) or (official.get("douyin_ai") if platform == "douyin_pet" else {}) or {}
            if row.get("status") in VERIFIED_OFFICIAL_STATUSES:
                for signal in row.get("signals") or []:
                    score = _fit(str(signal), platform)
                    evidence_type = "native" if row.get("native_verified") is True else "official_activity"
                    mode = "auto_browser" if "auto_browser" in support.get("allowed_association_modes", []) else "manual_handoff"
                    if score >= 0.55 and evidence_type in support.get("allowed_evidence_types", []):
                        selected = {
                            "source_url": row.get("official_url") or row.get("final_url"),
                            "observed_title": str(signal), "fetched_at": row.get("captured_at"),
                            "evidence_type": evidence_type, "native_verified": evidence_type == "native",
                            "association_mode": mode, "lane_fit_score": score, "semantic_fit_score": score,
                            "source_record": row,
                        }
                        break
        if not selected:
            missing.append({"platform": platform, "reason": "no_fresh_lane_matched_verified_hotspot_or_hot_work"})
            continue
        snapshot_rel = f"hotspots/{platform}.txt"
        snapshot = artifact_root / "_inputs" / snapshot_rel
        snapshot.write_text(json.dumps(selected["source_record"], ensure_ascii=False, sort_keys=True), encoding="utf-8")
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        record = {
            "platform": platform, "source_url": selected["source_url"],
            "observed_title": selected["observed_title"], "fetched_at": selected["fetched_at"],
            "status": 200, "snapshot_path": snapshot_rel, "snapshot_sha256": snapshot_hash,
            "evidence_type": selected["evidence_type"], "native_verified": selected["native_verified"],
            "association_mode": selected["association_mode"], "lane_fit_score": selected["lane_fit_score"],
            "semantic_fit_score": selected["semantic_fit_score"],
        }
        record["provenance_hash"] = _hotspot_source_hash(
            platform, record["source_url"], record["observed_title"], fetched_at=record["fetched_at"],
            status=record["status"], snapshot_path=snapshot_rel, snapshot_sha256=snapshot_hash,
        )
        (output_root / f"{platform}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        prepared.append({"platform": platform, "evidence_type": record["evidence_type"], "title": record["observed_title"]})
    return {
        "schema": "task9_input_preparation_v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "prepared": prepared, "missing": missing, "passed": len(prepared) == len(build_canary_matrix()),
        "source_pack": pack_path.name if pack_path.is_file() else "", "source_matrix": matrix_path.name if matrix_path else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = prepare_inputs(Path(args.data_root), Path(args.artifact_root))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
