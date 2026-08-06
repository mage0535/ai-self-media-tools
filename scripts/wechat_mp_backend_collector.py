"""Collect WeChat Official Account backend metrics from a local logged-in browser.

This collector is intended for accounts that cannot use the official Datacube
API. It keeps the browser login profile on the operator machine, exports only
numeric metrics, and can push the sanitized JSON to a Hermes deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = Path.home() / ".ai-self-media-tools" / "wechat_mp_profile"
DEFAULT_OUTPUT = Path.home() / ".ai-self-media-tools" / "wechat_mp_metrics.json"
MP_HOME = "https://mp.weixin.qq.com/"


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - exercised in operator envs.
        raise SystemExit(
            "Playwright is required. Install it in the local runtime and run "
            "`python -m playwright install chromium`."
        ) from exc
    return sync_playwright


def _launch_context(profile_dir: Path, *, headless: bool, state_file: Path | None = None):
    sync_playwright = _load_playwright()
    pw = sync_playwright().start()
    common = {
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1280, "height": 900},
    }
    if state_file:
        browser = pw.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=zh-CN"])
        context = browser.new_context(storage_state=str(_normalize_state_file(state_file)), **common)
        return pw, context
    profile_dir.mkdir(parents=True, exist_ok=True)
    context = pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=zh-CN"],
        **common,
    )
    return pw, context


def login(profile_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    pw, context = _launch_context(profile_dir, headless=False)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(MP_HOME, wait_until="domcontentloaded", timeout=90_000)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            url = page.url or ""
            if _is_logged_in_url(url):
                return {"status": "ok", "logged_in": True, "profile_dir": str(profile_dir)}
        return {"status": "timeout", "logged_in": False, "profile_dir": str(profile_dir)}
    finally:
        context.close()
        pw.stop()


def collect(profile_dir: Path, output: Path, *, days: int, headless: bool, state_file: Path | None = None) -> dict[str, Any]:
    begin = date.today() - timedelta(days=days)
    end = date.today() - timedelta(days=1)
    pw, context = _launch_context(profile_dir, headless=headless, state_file=state_file)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(MP_HOME, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(3000)
        home_text = ""
        try:
            home_text = page.locator("body").inner_text(timeout=10_000)
        except Exception:
            home_text = ""
        if not _is_logged_in_url(page.url or ""):
            # Some sessions need the analytics page to trigger the logged-in route.
            page.goto(
                f"https://mp.weixin.qq.com/cgi-bin/useranalysis?t=user/index_frame&lang=zh_CN",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_timeout(5000)
            try:
                home_text = page.locator("body").inner_text(timeout=10_000)
            except Exception:
                pass
        if not _is_logged_in_url(page.url or ""):
            return _write_report(
                output,
                status="login_required",
                reason="mp.weixin.qq.com profile is not logged in or requires verification",
                records=[],
            )

        token = _extract_token(page.url or "")
        home_metrics = _parse_home_summary(home_text)
        page.goto(
            "https://mp.weixin.qq.com/cgi-bin/useranalysis"
            f"?t=user/index_frame&lang=zh_CN&token={token}",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        page.wait_for_timeout(8000)
        text = page.locator("body").inner_text(timeout=30_000)
        if _looks_logged_out(text):
            if home_metrics:
                metrics = {
                    "source": "mp.weixin.qq.com backend home visible metrics",
                    "date_range_days": days,
                    "begin_date": begin.isoformat(),
                    "end_date": end.isoformat(),
                    "backend_login_verified": 1,
                    **home_metrics,
                }
                record = {
                    "job_id": f"wechat-backend-snapshot-{date.today().isoformat()}",
                    "platform": "wechat",
                    "views": int(metrics.get("yesterday_reads", 0) or 0),
                    "shares": int(metrics.get("yesterday_shares", 0) or 0),
                    "follows": int(metrics.get("new_followers", 0) or 0),
                    "metrics": metrics,
                }
                return _write_report(output, status="ok", reason="", records=[record])
            return _write_report(
                output,
                status="login_required",
                reason="mp.weixin.qq.com backend reports login timeout or requires scan login",
                records=[],
            )
        follower_metrics = _parse_follower_summary(text)
        article_summary = _fetch_article_summary(page, token)
        metrics = {
            "source": "mp.weixin.qq.com backend visible useranalysis",
            "date_range_days": days,
            "begin_date": begin.isoformat(),
            "end_date": end.isoformat(),
            "backend_login_verified": 1,
            **follower_metrics,
            **article_summary,
        }
        core_total = sum(
            int(metrics.get(key, 0) or 0)
            for key in ("new_followers", "unfollowers", "net_followers", "total_followers", "article_count_visible")
        )
        if core_total <= 0:
            return _write_report(
                output,
                status="loaded_but_metrics_not_visible",
                reason="mp.weixin backend opened but follower/article metrics were not visible; refresh login profile or update selectors",
                records=[],
            )
        follows = int(metrics.get("new_followers", 0) or 0)
        record = {
            "job_id": f"wechat-backend-snapshot-{date.today().isoformat()}",
            "platform": "wechat",
            "follows": follows,
            "metrics": metrics,
        }
        return _write_report(output, status="ok", reason="", records=[record])
    finally:
        context.close()
        pw.stop()


def push_hermes(output: Path, ssh_target: str, ssh_key: str, ssh_port: int, remote_project: str) -> dict[str, Any]:
    if not output.is_file():
        raise SystemExit(f"metrics file does not exist: {output}")
    remote_metrics = f"/tmp/{output.name}"
    scp_cmd = [
        "scp",
        "-q",
        "-o",
        "BatchMode=yes",
        "-i",
        ssh_key,
        "-P",
        str(ssh_port),
        str(output),
        f"{ssh_target}:{remote_metrics}",
    ]
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-i",
        ssh_key,
        "-p",
        str(ssh_port),
        ssh_target,
        (
            f"cd {remote_project} && "
            f"PYTHONPATH=. python3 -m content_platform.cli --db data/state.db "
            f"performance-import --allow-unknown-job {remote_metrics} && "
            "PYTHONPATH=. python3 - <<'PY'\n"
            "from content_platform.store import Store\n"
            "from content_platform.performance_cycle import _refresh_growth_strategies\n"
            "store=Store('data/state.db')\n"
            "_refresh_growth_strategies(store, ['wechat'])\n"
            "print('wechat_growth_strategy_refreshed')\n"
            "PY"
        ),
    ]
    subprocess.run(scp_cmd, check=True)
    completed = subprocess.run(ssh_cmd, check=True, text=True, capture_output=True)
    return {"status": "ok", "remote_metrics": remote_metrics, "stdout": completed.stdout.strip()}


def _is_logged_in_url(url: str) -> bool:
    return any(marker in url for marker in ("cgi-bin/home", "cgi-bin/useranalysis", "cgi-bin/appmsg"))


def _looks_logged_out(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in ("登录超时", "重新登录", "扫码", "二维码", "login", "sign in"))


def _normalize_state_file(path: Path) -> Path:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cookies" in data:
        return path
    raw_cookies = data
    if isinstance(data, dict) and isinstance(data.get("cookie_info"), list):
        raw_cookies = data["cookie_info"]
    if not isinstance(raw_cookies, list):
        raise ValueError("state file must be Playwright storage_state JSON, a cookie list, or SAU cookie_info JSON")
    cookies = []
    for item in raw_cookies:
        if not isinstance(item, dict):
            continue
        cookie = {
            "name": str(item.get("name") or ""),
            "value": str(item.get("value") or ""),
            "domain": str(item.get("domain") or item.get("host") or ""),
            "path": str(item.get("path") or "/"),
            "httpOnly": bool(item.get("httpOnly", item.get("http_only", False))),
            "secure": bool(item.get("secure", True)),
        }
        expires = item.get("expires", item.get("expirationDate", -1))
        try:
            cookie["expires"] = int(float(expires))
        except (TypeError, ValueError):
            cookie["expires"] = -1
        same_site = str(item.get("sameSite") or "Lax").capitalize()
        cookie["sameSite"] = same_site if same_site in {"Strict", "Lax", "None"} else "Lax"
        if cookie["name"] and cookie["value"] and cookie["domain"]:
            cookies.append(cookie)
    tmp = Path(tempfile.gettempdir()) / f"wechat_mp_storage_state_{abs(hash(str(path)))}.json"
    tmp.write_text(json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False), encoding="utf-8")
    return tmp


def _extract_token(url: str) -> str:
    match = re.search(r"[?&]token=(\d+)", url)
    return match.group(1) if match else ""


def _parse_follower_summary(text: str) -> dict[str, int]:
    labels = {
        "new_followers": "新关注人数",
        "unfollowers": "取消关注人数",
        "net_followers": "净增关注人数",
        "total_followers": "累计关注人数",
    }
    metrics: dict[str, int] = {}
    for key, label in labels.items():
        metrics[key] = _number_after_label(text, label)
    return metrics


def _parse_home_summary(text: str) -> dict[str, int]:
    labels = {
        "total_followers": "总用户数",
        "yesterday_reads": "昨日阅读",
        "yesterday_shares": "昨日分享",
        "new_followers": "昨日新增关注",
        "original_content_count": "原创内容",
    }
    metrics: dict[str, int] = {}
    for key, label in labels.items():
        value = _number_after_label(text, label)
        if value:
            metrics[key] = value
    return metrics


def _number_after_label(text: str, label: str) -> int:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if label in line:
            for candidate in lines[index + 1 : index + 5]:
                match = re.search(r"-?\d[\d,]*", candidate)
                if match:
                    return int(match.group(0).replace(",", ""))
    return 0


def _fetch_article_summary(page: Any, token: str) -> dict[str, int]:
    if not token:
        return {"article_count_visible": 0}
    script = """
    async (token) => {
      const url = '/cgi-bin/appmsg?action=list_ex&begin=0&count=5&query=&fakeid=&type=9&token=' + token + '&lang=zh_CN&f=json&ajax=1';
      const response = await fetch(url, {credentials: 'include'});
      const payload = await response.json();
      return {article_count_visible: Number(payload.app_msg_cnt || 0), latest_article_count: Array.isArray(payload.app_msg_list) ? payload.app_msg_list.length : 0};
    }
    """
    try:
        result = page.evaluate(script, token)
    except Exception:
        return {"article_count_visible": 0}
    return {key: int(value or 0) for key, value in dict(result or {}).items()}


def _write_report(output: Path, *, status: str, reason: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    report = {"status": status, "reason": reason, "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    login_cmd = sub.add_parser("login")
    login_cmd.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    login_cmd.add_argument("--timeout-seconds", type=int, default=900)
    collect_cmd = sub.add_parser("collect")
    collect_cmd.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    collect_cmd.add_argument("--state-file", type=Path, default=None, help="Optional Playwright storage_state, cookie list, or SAU cookie_info JSON")
    collect_cmd.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    collect_cmd.add_argument("--days", type=int, default=30)
    collect_cmd.add_argument("--headed", action="store_true", help="Show the browser while collecting")
    push_cmd = sub.add_parser("push-hermes")
    push_cmd.add_argument("--metrics-file", type=Path, default=DEFAULT_OUTPUT)
    push_cmd.add_argument("--ssh-target", required=True)
    push_cmd.add_argument("--ssh-key", required=True)
    push_cmd.add_argument("--ssh-port", type=int, default=22)
    push_cmd.add_argument("--remote-project", default=os.environ.get("AI_SELF_MEDIA_HOME", "~/.ai-self-media-tools"))
    args = parser.parse_args(argv)

    if args.command == "login":
        result = login(args.profile_dir, args.timeout_seconds)
    elif args.command == "collect":
        result = collect(args.profile_dir, args.output, days=args.days, headless=not args.headed, state_file=args.state_file)
    else:
        result = push_hermes(args.metrics_file, args.ssh_target, args.ssh_key, args.ssh_port, args.remote_project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
