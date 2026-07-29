"""Video Channels management-page postcheck helper.

This script is intended to run on Hermes where social-auto-upload and the
Tencent uploader browser state exist. It does not print cookie contents.
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

from patchright.async_api import async_playwright


DEFAULT_ACCOUNT = "/root/social-auto-upload/cookies/tencent_uploader/main.json"
DEFAULT_OUT_DIR = "/root/.ai-self-media-tools/data/local_ops_shipinhao/postcheck"
SOCIAL_AUTO_UPLOAD = os.environ.get("SOCIAL_AUTO_UPLOAD_DIR", "/root/social-auto-upload")


def _load_social_auto_upload() -> None:
    if SOCIAL_AUTO_UPLOAD not in sys.path:
        sys.path.insert(0, SOCIAL_AUTO_UPLOAD)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - evidence should record malformed JSON.
        return {"_read_error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def _load_targets(args: argparse.Namespace) -> list[str]:
    targets = [target.strip() for target in args.title if target.strip()]
    for manifest_value in args.manifest:
        manifest = _read_json(Path(manifest_value))
        for field in ["title", "short_title"]:
            value = str(manifest.get(field, "")).strip()
            if value:
                targets.append(value)
    if args.user_verified:
        user_verified = _read_json(Path(args.user_verified))
        value = str(user_verified.get("title", "")).strip()
        if value:
            targets.append(value)
    unique_targets: list[str] = []
    for target in targets:
        if target not in unique_targets:
            unique_targets.append(target)
    return unique_targets


async def _snapshot(page: Any, out_dir: Path, name: str, targets: list[str]) -> dict[str, Any]:
    await page.wait_for_timeout(5000)
    body = ""
    try:
        body = await page.locator("body").first.inner_text(timeout=8000)
    except Exception as exc:  # noqa: BLE001 - page text failures are evidence.
        body = "BODY_READ_FAILED:" + repr(exc)
    screenshot = out_dir / f"{name}.png"
    await page.screenshot(path=str(screenshot), full_page=True)
    return {
        "name": name,
        "url": page.url,
        "found_targets": [target for target in targets if target and target in body],
        "login_like": "login.html" in page.url or "扫码登录" in body or "微信登录" in body,
        "body_head": body[:1800],
        "screenshot": str(screenshot),
    }


async def _try_actions(context: Any, out_dir: Path, name: str, targets: list[str], actions: list[tuple[str, Any]]) -> dict[str, Any]:
    page = await context.new_page()
    route: dict[str, Any] = {"route": name, "steps": [], "snapshots": []}
    try:
        await page.goto("https://channels.weixin.qq.com/platform", wait_until="domcontentloaded", timeout=60000)
        route["snapshots"].append(await _snapshot(page, out_dir, f"{name}_00_home", targets))
        for index, (step_name, action) in enumerate(actions, start=1):
            try:
                await action(page)
                route["steps"].append({"step": step_name, "ok": True, "url": page.url})
            except Exception as exc:  # noqa: BLE001 - route failures are evidence.
                route["steps"].append({"step": step_name, "ok": False, "url": page.url, "error": repr(exc)[:500]})
            route["snapshots"].append(await _snapshot(page, out_dir, f"{name}_{index:02d}_{step_name}", targets))
    finally:
        await page.close()
    route["found_targets"] = sorted({target for shot in route["snapshots"] for target in shot["found_targets"]})
    route["login_like"] = any(shot["login_like"] for shot in route["snapshots"])
    return route


async def run_postcheck(args: argparse.Namespace) -> dict[str, Any]:
    _load_social_auto_upload()
    from uploader.tencent_uploader.main import _build_launch_kwargs, _new_tencent_context

    targets = [target.strip() for target in args.title if target.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    user_verified = _read_json(Path(args.user_verified)) if args.user_verified else {}
    targets = _load_targets(args)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=not args.headful))
        context = await _new_tencent_context(browser, args.account)
        try:
            routes = [
                await _try_actions(
                    context,
                    out_dir,
                    "video_management_all_video",
                    targets,
                    [
                        ("click_content_management", lambda page: page.get_by_role("link", name="内容管理").click(force=True, timeout=10000)),
                        ("click_all_video", lambda page: page.get_by_text("全部视频", exact=False).click(force=True, timeout=10000)),
                    ],
                ),
                await _try_actions(
                    context,
                    out_dir,
                    "video_management_left_video",
                    targets,
                    [
                        ("click_content_management", lambda page: page.get_by_role("link", name="内容管理").click(force=True, timeout=10000)),
                        ("click_left_video", lambda page: page.mouse.click(86, 258)),
                    ],
                ),
                await _try_actions(
                    context,
                    out_dir,
                    "draft_box",
                    targets,
                    [
                        ("click_content_management", lambda page: page.get_by_role("link", name="内容管理").click(force=True, timeout=10000)),
                        ("click_draft_box", lambda page: page.mouse.click(96, 482)),
                    ],
                ),
            ]
        finally:
            await context.storage_state(path=args.account)
            await context.close()
            await browser.close()

    found_targets = sorted({target for route in routes for target in route["found_targets"]})
    login_like = any(route["login_like"] for route in routes)
    user_verified_status = str(user_verified.get("status", ""))
    user_verified_submit = user_verified_status.startswith("submitted_user_verified")

    if found_targets:
        status = "postcheck_found"
        completion_state = "drafted_or_scheduled_visible"
        duplicate_upload_blocked = True
    elif user_verified_submit:
        status = "submitted_user_verified_pending_platform_list_sync"
        completion_state = "handoff_pending"
        duplicate_upload_blocked = True
    elif login_like:
        status = "auth_required"
        completion_state = "blocked"
        duplicate_upload_blocked = False
    else:
        status = "not_found"
        completion_state = "blocked_or_unknown"
        duplicate_upload_blocked = False

    report = {
        "platform": "shipinhao",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "completion_state": completion_state,
        "targets": targets,
        "found_targets": found_targets,
        "duplicate_upload_blocked": duplicate_upload_blocked,
        "user_verified_status": user_verified_status or None,
        "routes": routes,
        "rule": "do_not_reupload_when_user_verified_submission_exists_even_if_management_list_has_not_synced",
    }
    report_path = out_dir / "shipinhao_postcheck_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "completion_state": completion_state, "found_targets": found_targets, "report": str(report_path)}, ensure_ascii=False))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Postcheck Video Channels management pages by title.")
    parser.add_argument("--title", action="append", default=[], help="Expected title or unique title fragment. Repeatable.")
    parser.add_argument("--manifest", action="append", default=[], help="UTF-8 publish_manifest.json path. Repeatable.")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT, help="Tencent uploader storage-state file on Hermes.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Ignored evidence output directory.")
    parser.add_argument("--user-verified", default="", help="Optional user_verified_submission.json path.")
    parser.add_argument("--headful", action="store_true", help="Run visible browser for manual diagnosis.")
    args = parser.parse_args()
    if not _load_targets(args):
        parser.error("at least one --title, --manifest title, or --user-verified title is required")
    return args


def main() -> None:
    asyncio.run(run_postcheck(parse_args()))


if __name__ == "__main__":
    main()
