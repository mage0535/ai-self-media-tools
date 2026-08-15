"""Kuaishou management-page postcheck from a publish manifest.

The script is designed for ignored runtime paths on Hermes. It never prints
cookie contents and reports missing browser state as a structured failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=2&from=publish"


def _write_report(out_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "postcheck.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ["passed", "status", "report", "evidence_path"]}, ensure_ascii=False))
    return report


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _expected_values(manifest: dict[str, Any]) -> dict[str, str]:
    title = str(manifest.get("title") or manifest.get("short_title") or "").strip()
    description = str(manifest.get("description") or manifest.get("caption") or "").strip()
    schedule_time = str(manifest.get("schedule_time") or manifest.get("scheduled_at") or "").strip()
    return {"title": title, "description": description, "schedule_time": schedule_time}


def _classify_management_postcheck(manifest: dict[str, Any], body: str) -> dict[str, Any]:
    expected = _expected_values(manifest)
    login_like = any(token in body for token in ["登录", "扫码", "验证码", "login"])
    under_review = "审核中" in body
    description_snippet = expected["description"][:40]
    title_found = bool(expected["title"] and expected["title"] in body)
    description_found = bool(description_snippet and description_snippet in body)
    schedule_found = bool(expected["schedule_time"] and expected["schedule_time"] in body)
    # An "under review" page can contain unrelated descriptions. Require both
    # expected title and description before attributing the row to this run.
    work_found = title_found and description_found
    if login_like:
        status = "login_required"
    elif under_review and work_found:
        status = "success_under_review"
    elif under_review:
        status = "under_review"
    else:
        status = "management_postcheck_found" if title_found and (not expected["schedule_time"] or schedule_found) else "management_postcheck_not_found"
    passed = (
        not login_like
        and (
            (under_review and work_found)
            or (title_found and (not expected["schedule_time"] or schedule_found))
        )
    )
    return {
        "passed": passed,
        "status": status,
        "title_found": title_found,
        "description_found": description_found,
        "schedule_found": schedule_found,
        "login_like": login_like,
        "expected_title": expected["title"],
        "expected_description_snippet": description_snippet,
        "expected_schedule_time": expected["schedule_time"],
        "delivery_state": "under_review" if status == "success_under_review" else "scheduled" if passed else "unverified",
    }


def _storage_state_path() -> Path:
    explicit = os.environ.get("KUAISHOU_STORAGE_STATE") or os.environ.get("KS_STORAGE_STATE")
    if explicit:
        return Path(explicit).expanduser()
    social_root = Path(os.environ.get("SOCIAL_AUTO_UPLOAD_DIR", str(Path.home() / "social-auto-upload"))).expanduser()
    candidates = [
        social_root / "cookies" / "ks_uploader" / "main.json",
        social_root / "cookies" / "ks_uploader" / "account.json",
        social_root / "cookies" / "kuaishou_main.json",
        social_root / "cookies" / "ks_main.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _cn_proxy() -> dict[str, str] | None:
    if str(os.environ.get("KUAISHOU_REQUIRE_CN_PROXY", "1")).casefold() in {"0", "false", "no", "off"}:
        return None
    raw = os.environ.get("CN_PROXY", "").strip()
    if not raw:
        raise RuntimeError("missing CN_PROXY for Kuaishou postcheck")
    if raw.startswith("socks5h://"):
        raw = "socks5://" + raw[len("socks5h://") :]
    return {"server": raw}


async def _run_browser_check(manifest: dict[str, Any], out_dir: Path, headless: bool) -> dict[str, Any]:
    try:
        from patchright.async_api import async_playwright
    except Exception:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {
                "passed": False,
                "status": "browser_dependency_missing",
                "error": f"missing patchright/playwright: {type(exc).__name__}",
            }

    expected = _expected_values(manifest)
    if not expected["title"] and not expected["description"]:
        return {"passed": False, "status": "manifest_missing_match_text"}

    storage_state = _storage_state_path()
    if not storage_state.is_file():
        return {
            "passed": False,
            "status": "storage_state_missing",
            "storage_state_configured": bool(os.environ.get("KUAISHOU_STORAGE_STATE") or os.environ.get("KS_STORAGE_STATE")),
        }
    try:
        proxy = _cn_proxy()
    except Exception as exc:
        return {
            "passed": False,
            "status": "cn_proxy_missing",
            "error": str(exc)[:200],
        }

    manage_url = os.environ.get("KUAISHOU_MANAGE_URL", DEFAULT_MANAGE_URL)
    evidence_path = out_dir / "kuaishou_management_postcheck.png"
    browser = None
    async with async_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        chromium_path = os.environ.get("KUAISHOU_CHROMIUM") or os.environ.get("CHROMIUM_EXECUTABLE")
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(storage_state=str(storage_state), locale="zh-CN")
        page = await context.new_page()
        try:
            await page.goto(manage_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(int(os.environ.get("KUAISHOU_POSTCHECK_WAIT_MS", "8000")))
            body = await page.locator("body").first.inner_text(timeout=10000)
            await page.screenshot(path=str(evidence_path), full_page=True)
        finally:
            await context.storage_state(path=str(storage_state))
            await context.close()
            await browser.close()

    report = _classify_management_postcheck(manifest, body)
    report.update({
        "url": page.url,
        "evidence_path": str(evidence_path),
        "body_head": body[:1200],
    })
    return report


async def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir).expanduser()
    try:
        manifest = _read_manifest(Path(args.manifest).expanduser())
    except Exception as exc:
        return _write_report(
            out_dir,
            {
                "platform": "kuaishou",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "passed": False,
                "status": "manifest_unavailable",
                "error": str(exc)[:300],
            },
        )
    report = await _run_browser_check(manifest, out_dir, headless=not args.headful)
    report.update(
        {
            "platform": "kuaishou",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manifest": str(Path(args.manifest).expanduser()),
            "rule": "completion requires management page title match and exact schedule time when schedule_time is present",
        }
    )
    return _write_report(out_dir, report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Kuaishou draft/scheduled work exists in management page.")
    parser.add_argument("manifest", help="Publish manifest JSON generated after social-auto-upload submission.")
    parser.add_argument("out_dir", help="Ignored evidence output directory.")
    parser.add_argument("--headful", action="store_true", help="Run visible browser for diagnosis.")
    return parser.parse_args()


def main() -> None:
    report = asyncio.run(run(parse_args()))
    sys.exit(0 if report.get("passed") else 2)


if __name__ == "__main__":
    main()
