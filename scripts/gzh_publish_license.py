#!/usr/bin/env python3
"""WeChat Official Account publish-license gate.

The gate is intentionally fail-closed in the caller. It checks the operational
cadence rules before a generated article is pushed to the draft box.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CST = timezone(timedelta(hours=8))
MAX_WECHAT_ARTICLES_PER_WEEK = 3
FORBIDDEN_HOURS = range(0, 6)
RECENT_WINDOW_DAYS = 7
HOMOGENY_KEYWORDS = ("实测", "自动化", "工具测评", "十大", "合集")


def project_home() -> Path:
    env_home = os.environ.get("CONTENT_PLATFORM_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    scripts_dir = Path(__file__).resolve().parent
    if scripts_dir.name == "scripts":
        return scripts_dir.parent
    return Path.cwd()


def recent_wechat_titles(root: Path, window_days: int = RECENT_WINDOW_DAYS) -> list[tuple[str, str]]:
    titles: list[tuple[str, str]] = []
    cutoff = datetime.now(CST) - timedelta(days=window_days)
    recap_dir = root / "data" / "local_ops_gzh"
    if recap_dir.is_dir():
        for path in recap_dir.glob("recap_*.md"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, CST)
            if mtime < cutoff:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            title = _extract_structured_recap_title(text)
            if title:
                titles.append((title, mtime.strftime("%Y-%m-%d %H:%M")))
    titles.extend(_recent_delivered_wechat_titles(root, cutoff))
    return _dedupe_titles(titles)


def _recent_delivered_wechat_titles(root: Path, cutoff: datetime) -> list[tuple[str, str]]:
    db = root / "data" / "state.db"
    if not db.is_file():
        return []
    cutoff_text = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    titles: list[tuple[str, str]] = []
    try:
        with sqlite3.connect(str(db)) as conn:
            receipt_rows = conn.execute(
                "SELECT COALESCE(NULLIF(j.title,''), j.topic), r.created_at "
                "FROM publish_receipts r JOIN jobs j ON j.id = r.job_id "
                "WHERE r.platform IN ('wechat','gzh','wechat_official') "
                "AND r.status IN ('created','drafted','published','handoff_pending') "
                "AND r.created_at >= ?",
                (cutoff_text,),
            ).fetchall()
            queue_rows = conn.execute(
                "SELECT COALESCE(NULLIF(j.title,''), j.topic), q.updated_at "
                "FROM delivery_queue q JOIN jobs j ON j.id = q.job_id "
                "WHERE q.platform IN ('wechat','gzh','wechat_official') "
                "AND q.state IN ('completed','handoff_ready') "
                "AND COALESCE(q.error,'') = '' "
                "AND q.updated_at >= ?",
                (cutoff_text,),
            ).fetchall()
    except sqlite3.Error:
        return []
    for title, created_at in [*receipt_rows, *queue_rows]:
        if title:
            titles.append((str(title), str(created_at)[:16]))
    return titles


def check_license(title: str, *, root: Path | None = None, skip_time: bool = False, direction: str = "") -> dict:
    root = Path(root) if root else project_home()
    recent = recent_wechat_titles(root)
    failures: list[str] = []
    if len(recent) >= MAX_WECHAT_ARTICLES_PER_WEEK:
        failures.append(
            "frequency_limit:"
            f"recent_7d={len(recent)} max={MAX_WECHAT_ARTICLES_PER_WEEK}"
        )
    if not skip_time:
        now = datetime.now(CST)
        if now.hour in FORBIDDEN_HOURS:
            failures.append(f"forbidden_publish_hour:{now.strftime('%H:%M')}")
    for previous, when in recent:
        score = title_similarity(previous, title)
        if score >= 0.45:
            failures.append(f"duplicate_title:{when}:similarity={score:.2f}")
    direction_conflicts = recent_direction_conflicts(root, direction)
    if direction_conflicts:
        platforms = ",".join(
            sorted({str(item.get("platform") or "") for item in direction_conflicts if item.get("platform")})
        )
        failures.append(f"duplicate_direction:{direction}:platforms={platforms}")
    hits = [word for word in HOMOGENY_KEYWORDS if word in title]
    if len(hits) >= 2:
        failures.append("homogeneous_title_keywords:" + ",".join(hits))
    return {
        "version": "gzh_publish_license_v1",
        "title": title,
        "passed": not failures,
        "failures": failures,
        "checks": {
            "recent_titles": [f"{item} ({when})" for item, when in recent[-5:]],
            "recent_count": len(recent),
            "direction": direction,
            "direction_conflict_count": len(direction_conflicts),
            "max_per_week": MAX_WECHAT_ARTICLES_PER_WEEK,
            "now_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        },
    }


def recent_direction_conflicts(root: Path, direction: str) -> list[dict]:
    if not str(direction or "").strip():
        return []
    try:
        from content_platform.ops_run import _normalized_direction, _recent_records
    except Exception:
        return []
    today = _latest_ops_run_date(Path(root)) or datetime.now(CST).strftime("%Y%m%d")
    normalized = _normalized_direction("", direction)
    return [
        item
        for item in _recent_records(Path(root), today, RECENT_WINDOW_DAYS)
        if str(item.get("direction") or "") == normalized
    ]


def _latest_ops_run_date(root: Path) -> str:
    runs = []
    for path in (root / "data" / "ops_runs").glob("*/run_manifest.json"):
        name = path.parent.name
        if re.fullmatch(r"\d{8}", name):
            runs.append(name)
    return max(runs) if runs else ""


def title_similarity(left: str, right: str) -> float:
    a = set(_normalize(left).split())
    b = set(_normalize(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _normalize(text: str) -> str:
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", str(text or "").casefold())
    return " ".join(parts)


def _extract_structured_recap_title(text: str) -> str:
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            return ""
        if str(payload.get("platform") or "").casefold() not in {"wechat", "gzh", "wechat_official"}:
            return ""
        has_delivery_evidence = bool(payload.get("media_id") or payload.get("platform_content_id"))
        if has_delivery_evidence and payload.get("title"):
            return str(payload["title"])
    except json.JSONDecodeError:
        pass
    return ""


def _dedupe_titles(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for title, when in rows:
        key = _normalize(title)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((title, when))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check WeChat Official Account publish license")
    parser.add_argument("--title", required=True)
    parser.add_argument("--direction", default="")
    parser.add_argument("--root", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--skip-time", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).expanduser() if args.root else None
    result = check_license(args.title.strip(), root=root, direction=args.direction.strip(), skip_time=args.skip_time)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
