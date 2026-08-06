#!/usr/bin/env python3
"""Find non-secret platform URLs in historical evidence files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PLATFORM_HOSTS = {
    "douyin": ("douyin.com",),
    "kuaishou": ("kuaishou.com",),
    "shipinhao": ("channels.weixin.qq.com", "weixin.qq.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
}

SECRET_RE = re.compile(r"(cookie|token|secret|password|authorization|session|csrf|sess)", re.I)
URL_RE = re.compile(r"https?://[^\s\"<>]+")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--platform", action="append", default=list(PLATFORM_HOSTS))
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    report = {"status": "ok", "platforms": {platform: [] for platform in args.platform}}
    for root in [Path(item) for item in args.root]:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not _safe_file(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if _looks_like_secret_file(path, text):
                continue
            urls = [_clean_url(url) for url in URL_RE.findall(text)]
            for platform in args.platform:
                hosts = PLATFORM_HOSTS.get(platform, ())
                hits = [url for url in urls if any(host in url for host in hosts)]
                if hits:
                    report["platforms"][platform].append({"file": str(path), "urls": list(dict.fromkeys(hits))[:8]})
    for platform, items in report["platforms"].items():
        report["platforms"][platform] = items[:50]
    report["summary"] = {platform: len(items) for platform, items in report["platforms"].items()}
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace") + b"\n")
    return 0


def _safe_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size > 1_000_000:
        return False
    if path.suffix.lower() not in {".json", ".md", ".txt", ".html", ".log"}:
        return False
    return not SECRET_RE.search(str(path))


def _looks_like_secret_file(path: Path, text: str) -> bool:
    sample = text[:1000]
    return bool(SECRET_RE.search(path.name) or ("cookies" in sample and ("value" in sample or "sameSite" in sample)))


def _clean_url(url: str) -> str:
    return url.rstrip(".,);]}")


if __name__ == "__main__":
    raise SystemExit(main())
