#!/usr/bin/env python3
"""Discover and optionally save public profile URLs for metrics fallback.

The script is conservative: it only writes a URL when the page exposes at least
one visible numeric account signal through the normal performance collector.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from content_platform.performance_collectors import collect_platform_metrics


PLATFORM_HOST_HINTS = {
    "douyin": ("douyin.com",),
    "kuaishou": ("kuaishou.com",),
    "shipinhao": ("channels.weixin.qq.com", "weixin.qq.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "tiktok": ("tiktok.com",),
}

DEFAULT_QUERIES = {
    "douyin": ["\u732b\u54aa\u6cbb\u6108\u65e5\u8bb0 \u6296\u97f3", "\u9a6c\u5409\u514bAI \u6296\u97f3"],
    "kuaishou": ["\u9a6c\u5409\u514bAI \u5feb\u624b", "wordMagic \u5feb\u624b"],
    "shipinhao": ["\u9a6c\u5409\u514bAI \u89c6\u9891\u53f7", "wordMagic \u89c6\u9891\u53f7"],
    "xiaohongshu": ["\u9a6c\u5409\u514bAI \u5c0f\u7ea2\u4e66", "\u732b\u54aa\u6cbb\u6108\u65e5\u8bb0 \u5c0f\u7ea2\u4e66"],
    "tiktok": ["wordMagic TikTok", "Magic AI TikTok"],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-config", required=True, help="Private performance collector JSON")
    parser.add_argument("--platform", action="append", required=True)
    parser.add_argument("--query", action="append", default=[], help="Extra query as platform=query")
    parser.add_argument("--hints", default="", help="Optional JSON {platform:[query,...]}")
    parser.add_argument("--output", default="")
    parser.add_argument("--apply", action="store_true", help="Write verified URLs into collector config")
    args = parser.parse_args(argv)

    config_path = Path(args.collector_config)
    config = _load_json(config_path) if config_path.is_file() else {}
    queries = _queries(args.platform, args.query, args.hints)
    report = {"status": "ok", "platforms": {}}
    changed = False
    for platform in args.platform:
        candidates = _candidate_urls(platform, queries.get(platform, []))
        verified = []
        for url in candidates:
            probe_cfg = {platform: {"public_profile_url": url}}
            result = collect_platform_metrics([platform], probe_cfg)["platforms"][platform]
            if result.get("status") == "public_signal":
                verified.append({"url": url, "metrics": result.get("account_metrics", {})})
                break
        item = {
            "queries": queries.get(platform, []),
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
            "verified": verified,
            "status": "verified" if verified else "not_verified",
        }
        if args.apply and verified:
            config.setdefault(platform, {})
            if isinstance(config[platform], dict):
                config[platform]["public_profile_url"] = verified[0]["url"]
                changed = True
                item["applied"] = True
        report["platforms"][platform] = item
    if args.apply and changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        report["config_updated"] = str(config_path)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _queries(platforms: list[str], extra: list[str], hints_path: str) -> dict[str, list[str]]:
    queries = {platform: list(DEFAULT_QUERIES.get(platform, [])) for platform in platforms}
    if hints_path:
        hints = _load_json(Path(hints_path))
        for platform, items in hints.items():
            if isinstance(items, list):
                queries.setdefault(platform, []).extend(str(item) for item in items if str(item).strip())
    for item in extra:
        if "=" not in item:
            continue
        platform, query = item.split("=", 1)
        queries.setdefault(platform.strip(), []).append(query.strip())
    return {platform: list(dict.fromkeys(items)) for platform, items in queries.items()}


def _candidate_urls(platform: str, queries: list[str]) -> list[str]:
    candidates: list[str] = []
    for query in queries:
        for url in _search_web(query):
            if _is_platform_url(platform, url):
                candidates.append(_clean_url(url))
    return list(dict.fromkeys(candidates))


def _search_web(query: str) -> list[str]:
    urls: list[str] = []
    for searcher in (_search_bing, _search_baidu, _search_duckduckgo):
        for url in searcher(query):
            urls.append(url)
    return list(dict.fromkeys(urls))


def _search_bing(query: str) -> list[str]:
    search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    return _extract_search_urls(search_url)


def _search_baidu(query: str) -> list[str]:
    search_url = "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query})
    return _extract_search_urls(search_url)


def _search_duckduckgo(query: str) -> list[str]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    return _extract_search_urls(url)


def _extract_search_urls(url: str) -> list[str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    urls = []
    for raw in re.findall(r'href="([^"]+)"', html):
        raw = raw.replace("&amp;", "&")
        if "uddg=" in raw:
            parsed = urllib.parse.urlparse(raw)
            qs = urllib.parse.parse_qs(parsed.query)
            raw = qs.get("uddg", [raw])[0]
        if raw.startswith("http"):
            urls.append(urllib.parse.unquote(raw))
    return urls


def _is_platform_url(platform: str, url: str) -> bool:
    hosts = PLATFORM_HOST_HINTS.get(platform, ())
    return any(host in url for host in hosts)


def _clean_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


if __name__ == "__main__":
    raise SystemExit(main())
