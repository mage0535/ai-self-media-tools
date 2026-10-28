"""Typed parser for public Juejin article pages (same-lane benchmark samples).

Only public pages from the AI hot ranking are read, without login, a few per
night.  The raw page is kept so the breakdown can be re-verified from bytes.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE = "native.juejin_article"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_META = re.compile(r'<meta itemprop="(headline|datePublished|name)" content="([^"]*)"')


def parse_article_html(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8", errors="replace")
    meta: dict[str, str] = {}
    for key, value in _META.findall(text):
        meta.setdefault(key, html.unescape(value))  # the first "name" is the author
    start = text.find("markdown-body")
    end = text.find("</article>", start)
    if start < 0 or end < 0:
        raise ValueError("juejin_article_body_missing")
    segment = re.sub(r"<style[^>]*>.*?</style>", "", text[text.rfind("<div", 0, start):end], flags=re.S)
    body = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", segment))).strip()
    if not body or not meta.get("headline") or not meta.get("datePublished") or not meta.get("name"):
        raise ValueError("juejin_article_fields_missing")
    published = datetime.fromisoformat(meta["datePublished"].replace("Z", "+00:00"))
    return {"title": meta["headline"], "author": meta["name"], "published_at": published.isoformat(), "body": body}


def collect_samples(hot_items: list[dict[str, Any]], out_dir: str | Path, *, limit: int = 3,
                    fetch=None) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` public hot articles; a page that fails to parse is skipped."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fetch = fetch or _fetch
    rows = []
    for item in hot_items:
        if len(rows) >= limit:
            break
        match = re.fullmatch(r"https://juejin\.cn/post/(\d+)", str(item.get("url") or ""))
        if not match:
            continue
        try:
            raw = fetch(item["url"])
            parsed = parse_article_html(raw)
        except Exception:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        path = directory / f"juejin-{match.group(1)}-{digest[:12]}.html"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        rows.append({
            "platform": "juejin", "source": SOURCE, "content_id": match.group(1),
            "canonical_url": item["url"], "url": item["url"], **parsed,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metrics": {"hot_rank": int(item.get("points") or 0)},
            "raw_response_path": str(path), "raw_response_hash": digest,
        })
    return rows


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(2_000_000)


def verify_sample(row: dict[str, Any], raw: bytes) -> bool:
    """The stored body must be exactly what the stored raw page yields."""
    parsed = parse_article_html(raw)
    return all(row.get(key) == parsed[key] for key in ("title", "author", "published_at", "body"))


if __name__ == "__main__":  # manual check: python -m content_platform.juejin_native_article URL
    import sys

    print(json.dumps({k: (v[:120] if isinstance(v, str) else v)
                      for k, v in parse_article_html(_fetch(sys.argv[1])).items()}, ensure_ascii=False))
