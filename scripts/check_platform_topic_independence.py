#!/usr/bin/env python3
"""Check that each platform used independent source evidence before topic selection."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from content_platform.paths import project_home
except Exception:  # pragma: no cover
    def project_home() -> Path:
        import os

        return Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.cwd()))


PLATFORM_DIRS = {
    "wechat": "data/local_ops_gzh",
    "kuaishou": "data/local_ops_kuaishou",
    "bilibili": "data/local_ops_bilibili",
    "zhihu": "data/local_ops_zhihu",
    "juejin": "data/local_ops_juejin",
    "douyin": "data/local_ops_douyin",
    "shipinhao": "data/local_ops_shipinhao",
    "xiaohongshu": "data/local_ops_xiaohongshu",
    "youtube": "data/local_ops_youtube",
    "tiktok": "data/local_ops_tiktok",
    "x": "data/local_ops_x",
}


def _similarity(a: str, b: str) -> float:
    left = {ch for ch in a.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
    right = {ch for ch in b.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _load_analysis(platform_dir: Path, date: str) -> dict:
    json_candidates = [
        platform_dir / f"platform_source_matrix_{date}.json",
        platform_dir / f"analysis_{date}.json",
        platform_dir / f"ops_analysis_{date}.json",
    ]
    for path in json_candidates:
        if path.is_file():
            return {"path": str(path), "data": json.loads(path.read_text(encoding="utf-8"))}
    md = platform_dir / f"analysis_{date}.md"
    if md.is_file():
        text = md.read_text(encoding="utf-8", errors="replace")
        title = ""
        match = re.search(r"选题[：:]\s*(?:\*\*)?《?([^》\n*]+)", text)
        if match:
            title = match.group(1).strip()
        return {"path": str(md), "data": {"selected_topic": title, "markdown_only": True, "source_matrix": {}}}
    return {"path": "", "data": {}}


def _matrix_result(data: dict) -> dict:
    matrix = data.get("platform_source_matrix") or data.get("source_matrix") or {}
    if not isinstance(matrix, dict):
        matrix = {}
    attempted = matrix.get("attempted_sources") or data.get("attempted_sources") or []
    successful = matrix.get("successful_sources") or data.get("successful_sources") or []
    platform_internal = matrix.get("platform_internal_verified") or matrix.get("platform_internal_failure_reason")
    shared_only = bool(matrix.get("shared_trend_only") or data.get("shared_trend_only"))
    return {
        "attempted_count": len(attempted) if isinstance(attempted, list) else int(attempted or 0),
        "successful_count": len(successful) if isinstance(successful, list) else int(successful or 0),
        "platform_internal_evidence": bool(platform_internal),
        "shared_trend_only": shared_only,
    }


def check(date: str, platforms: list[str] | None = None, root: Path | None = None) -> dict:
    root = root or project_home()
    platforms = platforms or list(PLATFORM_DIRS)
    records = {}
    failures = []
    topics = {}
    for platform in platforms:
        loaded = _load_analysis(root / PLATFORM_DIRS.get(platform, f"data/local_ops_{platform}"), date)
        data = loaded["data"]
        selected = str(data.get("selected_topic") or data.get("topic") or data.get("title") or "").strip()
        matrix = _matrix_result(data)
        platform_failures = []
        if not loaded["path"]:
            platform_failures.append("analysis_file_missing")
        if matrix["attempted_count"] < 5:
            platform_failures.append("attempted_sources_lt_5")
        if matrix["successful_count"] < 3:
            platform_failures.append("successful_sources_lt_3")
        if not matrix["platform_internal_evidence"]:
            platform_failures.append("platform_internal_verification_missing")
        if matrix["shared_trend_only"]:
            platform_failures.append("shared_trend_only")
        if not selected:
            platform_failures.append("selected_topic_missing")
        if platform_failures:
            failures.append({"platform": platform, "failed_dimensions": platform_failures})
        records[platform] = {"analysis_path": loaded["path"], "selected_topic": selected, "matrix": matrix, "failed_dimensions": platform_failures}
        topics[platform] = selected

    for i, left in enumerate(platforms):
        for right in platforms[i + 1 :]:
            if topics.get(left) and topics.get(right) and _similarity(topics[left], topics[right]) > 0.72:
                failures.append({"platforms": [left, right], "failed_dimensions": ["topic_similarity_too_high"]})

    return {"passed": not failures, "date": date, "platforms": platforms, "records": records, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate per-platform topic/source independence.")
    parser.add_argument("date")
    parser.add_argument("--platforms", default="")
    parser.add_argument("--root", default="")
    args = parser.parse_args()
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()] or None
    result = check(args.date, platforms, Path(args.root) if args.root else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
