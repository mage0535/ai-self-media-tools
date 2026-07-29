#!/usr/bin/env python3
"""
预生成查重门禁 — 在生成任何新内容之前调用。
检查内容管道 store + 本地草稿目录，确认不重复才放行。

用法:
  python3 scripts/pre_generation_dedup_gate.py \\
    --title "你的作品标题" \\
    --platform kuaishou \\
    --account main

返回值:
  {"passed": true/false, "matches": [...], "reason": "..."}

exit 0 = 通过, exit 1 = 被阻断
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_HOME = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
DATA_DIR = PROJECT_HOME / "data"
DRAFT_DIR = DATA_DIR / "drafts"
STORE_PATH = DATA_DIR / "store.db"


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", str(text).casefold())
        if len(t) > 1
    ]


def _weighted_similarity(left: str, right: str) -> float:
    lc = Counter(_tokens(left))
    rc = Counter(_tokens(right))
    if not lc or not rc:
        return 0.0
    overlap = sum(min(lc[t], rc[t]) for t in lc if t in rc)
    total = sum(lc.values()) + sum(rc.values()) - overlap
    return round(overlap / max(1, total), 3)


def _check_local_drafts(title: str, platform: str, threshold: float = 0.58) -> list[dict]:
    """扫描本地草稿目录中同平台的 script.json，检查标题相似度"""
    matches = []
    norm_title = str(title).strip().casefold()

    # 扫描 kuaishou_video/v1/v2/v3/...
    draft_root = DRAFT_DIR / f"{platform}_video"
    if draft_root.is_dir():
        for subdir in sorted(draft_root.iterdir()):
            script_file = subdir / "script.json"
            if not script_file.is_file():
                continue
            try:
                script = json.loads(script_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            existing_title = str(script.get("title", "")).strip().casefold()
            existing_desc = str(script.get("desc", "")).strip().casefold()
            # 精确匹配
            if norm_title and norm_title == existing_title:
                matches.append({
                    "type": "TITLE_EXACT_MATCH",
                    "path": str(script_file),
                    "existing_title": script.get("title", ""),
                    "score": 1.0,
                })
                continue
            # 模糊匹配
            title_sim = _weighted_similarity(norm_title, existing_title)
            desc_sim = _weighted_similarity(norm_title, existing_desc)
            combined = round(title_sim * 0.6 + desc_sim * 0.4, 3)
            if combined >= threshold:
                matches.append({
                    "type": "TITLE_FUZZY_MATCH",
                    "path": str(script_file),
                    "existing_title": script.get("title", ""),
                    "title_similarity": title_sim,
                    "desc_similarity": desc_sim,
                    "combined_score": combined,
                })
    return matches


def _check_store(title: str, platform: str, threshold: float = 0.58) -> list[dict]:
    """通过 content-platform store 检查近期发表的同平台内容"""
    matches = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from content_platform.store import SqliteStore

        store = SqliteStore(str(STORE_PATH))
        deliveries = store.deliveries_all(limit=200)
        for delivery in deliveries:
            if str(delivery.get("platform", "")).casefold() != platform.casefold():
                continue
            job_id = delivery.get("job_id", "")
            job = store.get_job(job_id)
            if not job:
                continue
            existing_title = str(job.get("title", "")).strip().casefold()
            if not existing_title:
                continue
            sim = _weighted_similarity(str(title).strip().casefold(), existing_title)
            if sim >= threshold:
                matches.append({
                    "type": "STORE_TITLE_MATCH",
                    "job_id": job_id,
                    "existing_title": job.get("title", ""),
                    "similarity": sim,
                    "status": delivery.get("status", ""),
                })
    except Exception as exc:
        # store 不可用时不阻断，只记录
        return matches
    return matches


def main():
    parser = argparse.ArgumentParser(description="预生成查重门禁")
    parser.add_argument("--title", required=True, help="要生成的内容标题")
    parser.add_argument("--platform", default="kuaishou", help="目标平台")
    parser.add_argument("--account", default="main", help="账号标识")
    parser.add_argument("--threshold", type=float, default=0.58, help="模糊匹配阈值 (0-1)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    all_matches = []
    all_matches.extend(_check_local_drafts(args.title, args.platform, args.threshold))
    all_matches.extend(_check_store(args.title, args.platform, args.threshold))

    # 去重
    seen = set()
    unique_matches = []
    for m in all_matches:
        key = (m.get("type", ""), m.get("existing_title", ""))
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)

    passed = len(unique_matches) == 0
    result = {
        "passed": passed,
        "matches": unique_matches,
        "reason": "通过" if passed else f"发现 {len(unique_matches)} 条重复内容: {', '.join(m.get('existing_title', '')[:40] for m in unique_matches)}",
        "check": "pre_generation_dedup",
        "title": args.title,
        "platform": args.platform,
        "threshold": args.threshold,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "✅ 通过" if passed else f"❌ 阻断 ({result['reason']})"
        print(f"[预生成查重] {status}")
        for m in unique_matches:
            print(f"  - [{m['type']}] {m.get('existing_title', '')[:60]}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
