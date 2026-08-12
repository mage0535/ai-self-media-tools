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
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
            title = _extract_recap_title(text)
            if title:
                titles.append((title, mtime.strftime("%Y-%m-%d %H:%M")))
    db = root / "data" / "state.db"
    if db.is_file():
        try:
            with sqlite3.connect(str(db)) as conn:
                rows = conn.execute(
                    "SELECT title, created_at FROM jobs "
                    "WHERE (platforms_json LIKE '%wechat%' OR platforms_json LIKE '%gzh%') "
                    "AND created_at >= ?",
                    (cutoff.strftime("%Y-%m-%dT%H:%M:%S"),),
                ).fetchall()
            for title, created_at in rows:
                if title:
                    titles.append((str(title), str(created_at)[:16]))
        except sqlite3.Error:
            pass
    return _dedupe_titles(titles)


def check_license(title: str, *, root: Path | None = None, skip_time: bool = False) -> dict:
    root = root or project_home()
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
            "max_per_week": MAX_WECHAT_ARTICLES_PER_WEEK,
            "now_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        },
    }


def title_similarity(left: str, right: str) -> float:
    a = set(_normalize(left).split())
    b = set(_normalize(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _normalize(text: str) -> str:
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", str(text or "").casefold())
    return " ".join(parts)


def _extract_recap_title(text: str) -> str:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("title"):
            return str(payload["title"])
    except json.JSONDecodeError:
        pass
    patterns = [
        r'"title"\s*:\s*"([^"]{4,100})"',
        r"^title\s*[:：]\s*(.{4,100})$",
        r"^#\s+(.{4,100})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1).strip()
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
    parser.add_argument("--output", default="")
    parser.add_argument("--skip-time", action="store_true")
    args = parser.parse_args()
    result = check_license(args.title.strip(), skip_time=args.skip_time)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
