#!/usr/bin/env python3
"""Audit whether each platform has at least one usable metrics source configured."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PUBLIC_URL_KEYS = ("public_profile_url", "profile_url", "homepage_url", "public_url", "public_urls")
BACKEND_KEYS = (
    "state_file",
    "cookie_file",
    "datacube",
    "app_id",
    "channel_url",
    "mid",
    "uid",
    "metrics_file",
    "analytics_file",
    "api_url",
    "analytics_api_url",
)
STABLE_SOURCE_KEYS = {"api_url", "analytics_api_url", "metrics_file", "analytics_file", "public_profile_url", "profile_url", "homepage_url", "public_url", "public_urls"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Private collector JSON")
    parser.add_argument("--platform", action="append", default=[], help="Expected platform. Repeatable.")
    parser.add_argument("--output", default="", help="Optional JSON report path")
    args = parser.parse_args()

    path = Path(args.config)
    if not path.is_file():
        report = {"status": "missing_config", "config": str(path), "platforms": {}}
        return _finish(report, args.output)

    data = json.loads(path.read_text(encoding="utf-8"))
    platforms = args.platform or sorted(k for k, v in data.items() if isinstance(v, dict))
    report = {"status": "ok", "config": str(path), "platforms": {}}
    for platform in platforms:
        cfg = data.get(platform) if isinstance(data, dict) else {}
        if not isinstance(cfg, dict):
            cfg = {}
        backend = [key for key in BACKEND_KEYS if cfg.get(key)]
        public = [key for key in PUBLIC_URL_KEYS if cfg.get(key)]
        status = "configured" if backend or public else "missing_source"
        stable = [key for key in backend + public if key in STABLE_SOURCE_KEYS]
        if backend and not stable and platform not in {"youtube", "bilibili", "wechat"}:
            status = "backend_only"
        next_action = ""
        if not public and status != "configured":
            next_action = "add public_profile_url or a working authenticated collector"
        if platform == "tiktok" and status != "configured":
            next_action = "add TikTok api_url/analytics_api_url, metrics_file/analytics_file export, or public_profile_url; do not rely on Creator Center weak metrics alone"
        report["platforms"][platform] = {
            "status": status,
            "backend_sources": backend,
            "public_fallback_sources": public,
            "stable_sources": stable,
            "next_action": next_action,
        }
    missing = [p for p, item in report["platforms"].items() if item["status"] == "missing_source"]
    backend_only = [p for p, item in report["platforms"].items() if item["status"] == "backend_only"]
    report["summary"] = {
        "platform_count": len(platforms),
        "missing_source_count": len(missing),
        "backend_only_without_public_fallback_count": len(backend_only),
        "needs_attention": missing + backend_only,
    }
    return _finish(report, args.output)


def _finish(report: dict[str, Any], output: str) -> int:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
