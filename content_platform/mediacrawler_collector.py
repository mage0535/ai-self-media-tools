"""Same-genre hot works observed on the target platform itself through MediaCrawler (owner 11-02).

MediaCrawler runs unmodified in its own checkout and venv (NON-COMMERCIAL LEARNING LICENSE 1.1)
via scripts/mediacrawler_launch.py. The login is the account holder's QR scan, kept in the
root-only browser profile, or a stored cookie file. In scheduled runs a needed login or a
captcha stops the collection; nothing is retried or worked around.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MC_DIR = Path(os.environ.get("MEDIACRAWLER_DIR", "/srv/crawler-projects/mediacrawler"))
LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "mediacrawler_launch.py"
COOKIE_DIR = Path("/srv/ai-self-media-tools/external/social-auto-upload/cookies")
CODES = {"zhihu": "zhihu"}
# Stored logins that MediaCrawler can reuse; other platforms use the QR-scanned profile.
COOKIE_FILES = {"zhihu": COOKIE_DIR / "zhihu_main.json"}
KEYWORDS = {"zhihu": ("AI 落地 案例",)}
EXIT_REASONS = {3: "mediacrawler_login_required", 4: "mediacrawler_verification_required"}
MIN_BODY_CHARS = 300


def search(platform: str, out_dir: str | Path, *, keywords: tuple[str, ...] | None = None, limit: int = 15,
           unattended: bool = True, qr_png: str | Path | None = None, run=subprocess.run,
           timeout: int = 900) -> list[dict[str, Any]]:
    """One small keyword search; returns MediaCrawler's stored rows with the stored file's hash."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    cookie_file = COOKIE_FILES.get(platform)
    env = dict(os.environ, MC_UNATTENDED="1" if unattended else "0")
    if cookie_file and cookie_file.is_file():
        env["MC_COOKIE_FILE"] = str(cookie_file)
    if qr_png:
        env["MC_QR_PNG"] = str(qr_png)
    command = [str(MC_DIR / ".venv" / "bin" / "python"), str(LAUNCHER), "--platform", CODES[platform],
               "--lt", "cookie" if "MC_COOKIE_FILE" in env else "qrcode", "--type", "search",
               "--keywords", ",".join(keywords or KEYWORDS[platform]), "--get_comment", "no", "--headless", "yes",
               "--save_data_option", "json", "--save_data_path", str(out), "--crawler_max_notes_count", str(limit)]
    # The log can carry login state, so it is discarded and never quoted in the error.
    proc = run(command, cwd=MC_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
               check=False)
    if proc.returncode:
        raise ValueError(EXIT_REASONS.get(proc.returncode, f"mediacrawler_failed:rc={proc.returncode}"))
    rows = []
    for path in sorted((out / platform / "json").glob("search_contents_*.json")):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        rows += [dict(row, raw_response_path=str(path), raw_response_hash=digest) for row in json.loads(raw)]
    if not rows:
        raise ValueError("mediacrawler_no_results")
    return rows


def zhihu_samples(rows: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Most-upvoted full-text answers/articles, in the article-sample shape the Juejin collector uses."""
    from .real_world_ai_policy import classify_discovery_text

    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kept = [row for row in rows if len(str(row.get("content_text") or "")) >= MIN_BODY_CHARS and row.get("content_url")
            and classify_discovery_text(str(row.get("title") or ""), str(row["content_text"])[:800])["accepted"]]
    kept.sort(key=lambda row: int(row.get("voteup_count") or 0), reverse=True)
    return [{
        "platform": "zhihu", "source": "native.zhihu_mediacrawler", "content_id": str(row.get("content_id")),
        "canonical_url": row["content_url"], "url": row["content_url"], "title": row.get("title") or "",
        "author": row.get("user_nickname") or "", "body": row["content_text"], "content_type": row.get("content_type"),
        "published_at": datetime.fromtimestamp(int(row["created_time"]), timezone.utc).isoformat() if row.get("created_time") else "",
        "observed_at": observed_at,
        "metrics": {"like": int(row.get("voteup_count") or 0), "comment": int(row.get("comment_count") or 0)},
        "raw_response_path": row["raw_response_path"], "raw_response_hash": row["raw_response_hash"],
    } for row in kept[:limit]]


def verify_sample(row: dict[str, Any], raw: bytes) -> bool:
    """The sample must be exactly what the stored MediaCrawler file holds for its content id."""
    try:
        stored = [item for item in json.loads(raw) if str(item.get("content_id")) == row.get("content_id")]
    except (ValueError, AttributeError):
        return False
    return len(stored) == 1 and all((
        stored[0].get("content_text") == row.get("body"), stored[0].get("content_url") == row.get("canonical_url"),
        (stored[0].get("title") or "") == row.get("title"), (stored[0].get("user_nickname") or "") == row.get("author"),
        int(stored[0].get("voteup_count") or 0) == (row.get("metrics") or {}).get("like"),
        int(stored[0].get("comment_count") or 0) == (row.get("metrics") or {}).get("comment"),
    ))
