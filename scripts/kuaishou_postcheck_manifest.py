"""Kuaishou management-page postcheck from a publish manifest.

The script is designed for ignored runtime paths on Hermes. It never prints
cookie contents and reports missing browser state as a structured failure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=2&from=publish"
BEIJING = timezone(timedelta(hours=8))
MAX_PAGES = 5
MAX_SCROLLS = 8
CARD_EXTRACT_JS = r"""({title, description}) => {
  const selector = 'article,li,tr,[role="row"],'
    + '[data-testid*="video-card"],[data-testid*="video-item"],'
    + '[data-testid*="work-card"],[data-testid*="work-item"],'
    + '[class*="video-card"],[class*="videoCard"],[class*="VideoCard"],'
    + '[class*="video-item"],[class*="videoItem"],[class*="VideoItem"],'
    + '[class*="work-card"],[class*="workCard"],[class*="WorkCard"],'
    + '[class*="work-item"],[class*="workItem"],[class*="WorkItem"],'
    + '[class*="manage-item"],[class*="manageItem"]';
  const nodes = [...new Set(document.querySelectorAll(selector))];
  const visible = node => !!(node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
  const matches = nodes.filter(node => {
    const text = node.innerText || '';
    if (!visible(node) || text.length > 3000 || !text.includes(title) || !text.includes(description))
      return false;
    const children = nodes.filter(child => child !== node && node.contains(child) && visible(child));
    const titleChildren = children.filter(child => (child.innerText || '').includes(title));
    const descChildren = children.filter(child => (child.innerText || '').includes(description));
    if (titleChildren.length && descChildren.length
        && !children.some(child => (child.innerText || '').includes(title)
            && (child.innerText || '').includes(description))) return false;
    return true;
  });
  const leaves = matches.filter(node => !matches.some(child => child !== node && node.contains(child)));
  return leaves.slice(0, 80).map((node, index) => {
    node.setAttribute('data-hermes-postcheck-card', String(index));
    const link = node.querySelector('a[href]');
    return {
      text: node.innerText || '',
      work_id: node.getAttribute('data-id') || node.getAttribute('data-work-id') || '',
      work_url: link ? link.href : '',
      locator: '[data-hermes-postcheck-card="' + index + '"]'
    };
  });
}"""
SCROLL_JS = r"""() => {
  const containers = [...document.querySelectorAll('*')].filter(node => {
    const style = getComputedStyle(node);
    return node.scrollHeight > node.clientHeight + 100 && /auto|scroll/.test(style.overflowY);
  });
  const target = containers.find(node => node.querySelector('[data-hermes-postcheck-card]'))
    || containers.find(node => node.querySelector('article,li,tr,[role="row"],'
        + '[class*="video-item"],[class*="work-item"]'))
    || containers[0] || document.scrollingElement;
  if (!target) return {moved: false};
  const before = target.scrollTop;
  target.scrollTop += Math.max(900, target.clientHeight);
  return {moved: target.scrollTop > before};
}"""


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


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _beijing_schedule(value: str) -> str:
    if not value.strip():
        return ""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=BEIJING)
        return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def _card_schedule(text: str) -> str:
    pattern = (r"(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?\s*"
               r"(\d{1,2}):(\d{2})(?!\d)")
    schedule_lines = [line for line in text.splitlines()
                      if any(mark in line for mark in ("定时", "预约", "排期", "发布时间"))]
    dates = re.findall(pattern, "\n".join(schedule_lines))
    found = set()
    for year, month, day, hour, minute in dates:
        try:
            found.add(datetime(int(year), int(month), int(day), int(hour), int(minute)).strftime("%Y-%m-%d %H:%M"))
        except ValueError:
            continue
    return next(iter(found)) if len(found) == 1 else ""


def _field_on_card(text: str, expected: str, labels: tuple[str, ...]) -> bool:
    if not expected:
        return False
    for line in text.splitlines():
        value = re.sub(r"^(?:" + "|".join(labels) + r")\s*[:：]\s*", "", _normal(line))
        if value == _normal(expected):
            return True
    return False


def _classify_management_postcheck(manifest: dict[str, Any], cards: list[dict[str, str]],
                                   *, login_like: bool = False) -> dict[str, Any]:
    expected = _expected_values(manifest)
    expected_schedule = _beijing_schedule(expected["schedule_time"])
    base = {
        "passed": False, "status": "login_required" if login_like else "management_postcheck_not_found",
        "delivery_state": "unverified", "title_found": False, "description_found": False,
        "schedule_found": False, "login_like": login_like,
        "expected_title": expected["title"],
        "expected_description_snippet": expected["description"][:40],
        "expected_schedule_time": expected["schedule_time"],
    }
    if login_like or not expected["title"] or not expected["description"] or not expected_schedule:
        return base
    candidates = []
    for card in cards:
        text = str(card.get("text") or "")
        if not (_field_on_card(text, expected["title"], ("标题", "作品标题"))
                and _field_on_card(text, expected["description"], ("描述", "作品描述", "简介"))):
            continue
        schedule_ok = _card_schedule(text) == expected_schedule
        state_lines = [_normal(line).replace("状态：", "").replace("状态:", "") for line in text.splitlines()]
        if any(line in {"审核中", "待审核"} for line in state_lines):
            state = "under_review"
        elif schedule_ok and any(line in {"定时发布", "待发布", "已预约", "已排期", "定时发布中"}
                                 for line in state_lines):
            state = "scheduled"
        else:
            state = "unverified"
        if state == "unverified":
            continue
        identity = str(card.get("work_id") or card.get("work_url") or "").strip()
        if not identity:
            identity = "sha256:" + hashlib.sha256(_normal(text).encode("utf-8")).hexdigest()
        candidates.append((card, state, identity, schedule_ok))
    if len(candidates) != 1:
        base["status"] = "ambiguous_work" if candidates else base["status"]
        return base
    card, state, identity, schedule_ok = candidates[0]
    base.update({
        "passed": state != "unverified",
        "status": "success_under_review" if state == "under_review" else
                  "management_postcheck_found" if state == "scheduled" else "management_status_unverified",
        "delivery_state": state,
        "title_found": True, "description_found": True, "schedule_found": schedule_ok,
        "matched_work": {
            "title": expected["title"], "description": expected["description"],
            "schedule_time": expected["schedule_time"] if schedule_ok else "", "state": state,
            "work_id": identity, "work_url": str(card.get("work_url") or ""),
        },
        "matched_locator": str(card.get("locator") or ""),
    })
    return base


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
    if not expected["title"] or not expected["description"] or not _beijing_schedule(expected["schedule_time"]):
        return {"passed": False, "status": "manifest_missing_match_text"}

    storage_state = _storage_state_path()
    if not storage_state.is_file():
        return {
            "passed": False,
            "status": "storage_state_missing",
            "storage_state_configured": bool(os.environ.get("KUAISHOU_STORAGE_STATE") or os.environ.get("KS_STORAGE_STATE")),
        }
    manage_url = os.environ.get("KUAISHOU_MANAGE_URL", DEFAULT_MANAGE_URL)
    evidence_path = out_dir / "kuaishou_matched_work.png"
    page_evidence_path = out_dir / "kuaishou_management_page.png"
    browser = None
    async with async_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        chromium_path = os.environ.get("KUAISHOU_CHROMIUM") or os.environ.get("CHROMIUM_EXECUTABLE")
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(storage_state=str(storage_state), locale="zh-CN")
        page = await context.new_page()
        try:
            await page.goto(manage_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(int(os.environ.get("KUAISHOU_POSTCHECK_WAIT_MS", "8000")))
            found: dict[str, dict[str, str]] = {}
            exhausted = False
            login_like = False
            for page_number in range(MAX_PAGES):
                reached_end = False
                for scroll in range(MAX_SCROLLS):
                    login_like = ("/login" in page.url.lower()
                                  or await page.locator('input[type="password"]').count() > 0)
                    if login_like:
                        break
                    cards = await page.evaluate(CARD_EXTRACT_JS, expected)
                    for card in cards:
                        card["page_url"] = page.url
                        identity = card.get("work_id") or card.get("work_url") or hashlib.sha256(
                            _normal(card.get("text", "")).encode("utf-8")
                        ).hexdigest()
                        key = identity + ":" + hashlib.sha256(
                            _normal(card.get("text", "")).encode("utf-8")
                        ).hexdigest()
                        if key not in found:
                            found[key] = card
                            if _classify_management_postcheck(manifest, [card]).get("passed"):
                                await page.locator(card["locator"]).screenshot(path=str(evidence_path))
                                await page.screenshot(path=str(page_evidence_path), full_page=True)
                    scroll_state = await page.evaluate(SCROLL_JS)
                    if not scroll_state.get("moved"):
                        reached_end = True
                        break
                    await page.wait_for_timeout(500)
                if not reached_end:
                    exhausted = True
                if login_like:
                    break
                next_button = page.locator('.ant-pagination-next:not(.ant-pagination-disabled), '
                                           'button[aria-label="下一页"], button[aria-label="Next"], '
                                           'li[title="下一页"]:not(.ant-pagination-disabled)')
                if await next_button.count() == 0:
                    break
                if page_number == MAX_PAGES - 1:
                    exhausted = True
                    break
                await next_button.first.click()
                await page.wait_for_timeout(1000)
            report = _classify_management_postcheck(manifest, list(found.values()), login_like=login_like)
            if exhausted and report.get("passed"):
                report.update({"passed": False, "status": "search_limit_reached", "delivery_state": "unverified"})
            if not page_evidence_path.exists():
                await page.screenshot(path=str(page_evidence_path), full_page=True)
            report.update({
                "url": page.url,
                "evidence_path": str(evidence_path.resolve()) if evidence_path.is_file() else "",
                "page_evidence_path": str(page_evidence_path.resolve()),
                "searched_pages": page_number + 1,
                "searched_cards": len(found),
            })
        finally:
            await context.close()
            await browser.close()
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
            "rule": "one management card must match full title, description, Beijing schedule, and explicit status",
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
