#!/usr/bin/env python3
"""Probe creator-center metric pages with an existing browser storage state.

This is a private-runtime helper: it verifies whether a saved login state can
reach backend metric pages and records screenshot/text evidence. It does not
print or persist cookie values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TARGETS: dict[str, dict[str, Any]] = {
    "douyin": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://creator.douyin.com/creator-micro/content/manage",
            "https://creator.douyin.com/creator-micro/data/overview",
        ],
    },
    "shipinhao": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://channels.weixin.qq.com/platform/post/list",
            "https://channels.weixin.qq.com/platform",
        ],
    },
    "xiaohongshu": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://creator.xiaohongshu.com/creator/notes",
            "https://creator.xiaohongshu.com/creator/data",
        ],
    },
    "tiktok": {
        "proxy_env": "US_PROXY",
        "urls": [
            "https://www.tiktok.com/creator-center/content",
            "https://www.tiktok.com/creator-center/analytics",
        ],
    },
}

LOGIN_PATTERNS = [
    "\u767b\u5f55",
    "\u626b\u7801",
    "login",
    "sign in",
    "\u4e8c\u7ef4\u7801",
    "\u5b89\u5168\u9a8c\u8bc1",
    "\u9a8c\u8bc1\u7801",
]
METRIC_PATTERNS = [
    "\u64ad\u653e",
    "\u9605\u8bfb",
    "\u70b9\u8d5e",
    "\u8bc4\u8bba",
    "\u6536\u85cf",
    "\u5206\u4eab",
    "\u7c89\u4e1d",
    "\u5b8c\u64ad",
    "\u66dd\u5149",
    "views",
    "likes",
    "comments",
    "followers",
    "analytics",
]


def _load_config(path: str) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _merge_target(platform: str, config: dict[str, Any]) -> dict[str, Any]:
    target = dict(DEFAULT_TARGETS.get(platform, {}))
    override = config.get(platform, {}) if isinstance(config.get(platform), dict) else {}
    target.update(override)
    return target


def _proxy_config(value: str) -> dict[str, str] | None:
    return {"server": value} if value else None


def _compact_text(text: str, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def probe_platforms(platforms: list[str], config: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on private runtime
        return {
            "status": "playwright_unavailable",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "platforms": {},
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "ok",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "out_dir": str(out_dir),
        "platforms": {},
    }
    with sync_playwright() as pw:
        for platform in platforms:
            target = _merge_target(platform, config)
            state_file = str(target.get("state_file") or target.get("cookie_file") or "")
            item: dict[str, Any] = {
                "state_file_present": bool(state_file and Path(state_file).is_file()),
                "proxy_env": target.get("proxy_env", ""),
                "proxy_configured": bool(os.environ.get(str(target.get("proxy_env") or ""))),
                "pages": [],
            }
            if not item["state_file_present"]:
                item.update({"status": "login_required", "reason": "state_file missing"})
                report["platforms"][platform] = item
                continue
            try:
                browser = pw.chromium.launch(
                    headless=True,
                    proxy=_proxy_config(os.environ.get(str(target.get("proxy_env") or ""))),
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(storage_state=state_file, locale="zh-CN", viewport={"width": 1440, "height": 1200})
                for index, url in enumerate(target.get("urls") or []):
                    page = context.new_page()
                    record: dict[str, Any] = {"url": url}
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=int(target.get("timeout_ms") or 45000))
                        page.wait_for_timeout(int(target.get("settle_ms") or 8000))
                        try:
                            page.mouse.wheel(0, 900)
                            page.wait_for_timeout(2500)
                        except Exception:
                            pass
                        text = page.locator("body").inner_text(timeout=5000)
                        lower = text.casefold()
                        screenshot = out_dir / f"{platform}_{index}.png"
                        text_file = out_dir / f"{platform}_{index}.txt"
                        text_file.write_text(text, encoding="utf-8", errors="ignore")
                        page.screenshot(path=str(screenshot), full_page=True)
                        record.update(
                            {
                                "status": "page_loaded",
                                "final_url": page.url,
                                "title": page.title(),
                                "text_length": len(text),
                                "login_like": any(pattern.casefold() in lower for pattern in LOGIN_PATTERNS),
                                "metric_like": any(pattern.casefold() in lower for pattern in METRIC_PATTERNS),
                                "text_file": str(text_file),
                                "screenshot": str(screenshot),
                                "sample": _compact_text(text),
                            }
                        )
                    except Exception as exc:
                        record.update({"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:250]}"})
                    item["pages"].append(record)
                    try:
                        page.close()
                    except Exception:
                        pass
                context.close()
                browser.close()
                if any(page.get("login_like") for page in item["pages"]):
                    item["status"] = "login_required_or_verification"
                elif any(page.get("metric_like") for page in item["pages"]):
                    item["status"] = "backend_loaded"
                else:
                    item["status"] = "loaded_but_metrics_not_visible"
            except Exception as exc:
                item.update({"status": "probe_failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            report["platforms"][platform] = item
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", action="append", required=True)
    parser.add_argument("--config", default="")
    parser.add_argument("--out-dir", default="/tmp/platform_backend_metrics_probe")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = probe_platforms(args.platform, _load_config(args.config), Path(args.out_dir))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
