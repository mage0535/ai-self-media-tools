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
from datetime import date, datetime, timedelta, timezone
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
    browser = None
    try:
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
    except BaseException:
        try:
            if browser is not None:
                browser.close()
        finally:
            pw.stop()
        raise


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


def build_account_snapshot_record(
    metrics: dict[str, Any],
    *,
    days: int,
    begin_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Build an audit-only account snapshot, never a content-performance row."""
    snapshot_metrics = {
        **metrics,
        "metric_scope": "account_snapshot",
        "metric_window": "yesterday",
        "strategy_eligible": False,
        "strategy_ineligible_reason": "aggregate_account_metrics_have_no_article_identity",
    }
    return {
        "job_id": f"wechat-backend-snapshot-{date.today().isoformat()}",
        "platform": "wechat",
        "views": int(snapshot_metrics.get("yesterday_reads", 0) or 0),
        "shares": int(snapshot_metrics.get("yesterday_shares", 0) or 0),
        "follows": int(snapshot_metrics.get("new_followers", 0) or 0),
        "metrics": snapshot_metrics,
    }


def collect(
    profile_dir: Path,
    output: Path,
    *,
    days: int,
    headless: bool,
    state_file: Path | None = None,
    account_name: str = "",
) -> dict[str, Any]:
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
        # The user-analysis page may show a stale login warning while the
        # authorized session still accepts the article-analysis endpoints. Try
        # those official endpoints before downgrading to an aggregate snapshot.
        article_index = _fetch_article_index(page, token)
        article_analysis = _fetch_article_analysis(page, token)
        article_observations = build_article_metric_observations(
            article_analysis,
            article_index,
            account_name=account_name,
            observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        article_collection_audit = build_article_collection_audit(
            article_analysis,
            article_index,
            article_observations,
            account_name=account_name,
            article_analysis_requested=True,
        )
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
                record = build_account_snapshot_record(metrics, days=days, begin_date=begin.isoformat(), end_date=end.isoformat())
                return _write_report(
                    output,
                    status="ok",
                    reason="",
                    records=[record],
                    article_observations=article_observations,
                    article_collection_audit=article_collection_audit,
                )
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
        record = build_account_snapshot_record(metrics, days=days, begin_date=begin.isoformat(), end_date=end.isoformat())
        return _write_report(
            output,
            status="ok",
            reason="",
            records=[record],
            article_observations=article_observations,
            article_collection_audit=article_collection_audit,
        )
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


def _fetch_article_index(page: Any, token: str, *, count: int = 20) -> dict[str, dict[str, Any]]:
    """Return only stable article identities needed to join authorized analysis."""
    if not token:
        return {}
    script = """
    async ({token, count}) => {
      const params = new URLSearchParams({action: 'list_ex', begin: '0', count: String(count), query: '', fakeid: '', type: '9', token, lang: 'zh_CN', f: 'json', ajax: '1'});
      const response = await fetch('/cgi-bin/appmsg?' + params.toString(), {credentials: 'include'});
      if (!response.ok) return [];
      const payload = await response.json();
      const rows = Array.isArray(payload.app_msg_list) ? payload.app_msg_list : [];
      return rows.map(row => ({msg_id: String(row.appmsgid || row.aid || ''), item_idx: Number(row.itemidx || 1), link: String(row.link || ''), create_time: Number(row.create_time || 0)}));
    }
    """
    try:
        rows = page.evaluate(script, {"token": token, "count": max(1, min(int(count), 20))})
    except Exception:
        return {}
    return {
        f"{str(row.get('msg_id') or '').strip()}:{int(row.get('item_idx') or 0)}": dict(row)
        for row in rows if isinstance(row, dict) and str(row.get("msg_id") or "").strip()
    }


def build_article_metric_observations(
    analysis_payload: dict[str, Any],
    article_index: dict[str, dict[str, Any]],
    *,
    account_name: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Normalize authorized MP article-analysis rows without claiming a baseline.

    A row is an auditable raw observation, not a breakout verdict.  It becomes a
    G4 strategy sample only after the separate WeChat evidence gate validates a
    comparable same-account baseline.
    """
    account_name = str(account_name or "").strip()
    if not account_name:
        return []
    rows = analysis_payload.get("article_list") if isinstance(analysis_payload, dict) else []
    if not isinstance(rows, list):
        return []
    observations: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        msg_id = str(raw.get("msg_id") or "").strip()
        item_idx = raw.get("item_idx")
        title = str(raw.get("title") or "").strip()
        try:
            item_idx = int(item_idx or 0)
            metric_value = int(raw.get("total_read_uv") or 0)
        except (TypeError, ValueError):
            continue
        article = article_index.get(f"{msg_id}:{item_idx}") or {}
        canonical_url = str(article.get("link") or "").strip()
        created = article.get("create_time")
        try:
            published_at = datetime.fromtimestamp(int(created or 0), tz=timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError, OSError):
            published_at = ""
        if not all((msg_id, title, canonical_url, published_at)):
            continue
        observations.append(
            {
                "platform": "wechat",
                "source_kind": "authorized_backend_export",
                "canonical_url": canonical_url,
                "article_id": msg_id,
                "msgid": msg_id,
                "idx": item_idx,
                "account_name": account_name,
                "title": title,
                "published_at": published_at,
                "observed_at": observed_at,
                "metric_name": "total_read_uv",
                "metric_definition": "Unique readers shown by authorized WeChat MP article analysis",
                "metric_value": metric_value,
                "metric_window": str(raw.get("ref_date") or ""),
                "additional_metrics": {"read_uv_ratio": raw.get("read_uv_ratio")},
                "baseline_required": True,
            }
        )
    return observations


def build_article_collection_audit(
    analysis_payload: dict[str, Any],
    article_index: dict[str, dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    account_name: str,
    article_analysis_requested: bool = False,
) -> dict[str, Any]:
    """Return diagnostic counts only; never expose article titles or metrics."""
    rows = analysis_payload.get("article_list") if isinstance(analysis_payload, dict) else []
    return {
        "article_analysis_row_count": len(rows) if isinstance(rows, list) else 0,
        "article_index_count": len(article_index) if isinstance(article_index, dict) else 0,
        "article_observation_count": len(observations) if isinstance(observations, list) else 0,
        "account_name_provided": bool(str(account_name or "").strip()),
        "article_analysis_requested": bool(article_analysis_requested),
        "article_analysis_base_ret": analysis_payload.get("base_ret") if isinstance(analysis_payload, dict) else None,
        "article_analysis_error": str(analysis_payload.get("__error") or "")[:80] if isinstance(analysis_payload, dict) else "",
    }


def _fetch_article_analysis(page: Any, token: str, *, count: int = 20) -> dict[str, Any]:
    """Fetch article analysis with the authorized browser-context HTTP client.

    ``page.evaluate(fetch(...))`` can lose its execution context when the MP
    dashboard refreshes.  BrowserContext.request shares the same authorized
    session without exporting cookies or bypassing the official backend.
    """
    if not token:
        return {}
    url = (
        "https://mp.weixin.qq.com/misc/appmsganalysis?"
        f"action=all_article&begin=0&count={max(1, min(int(count), 20))}"
        f"&token={token}&lang=zh_CN&f=json&ajax=1"
    )
    try:
        response = page.request.get(
            url,
            timeout=30_000,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://mp.weixin.qq.com/",
            },
        )
    except Exception:
        return {"__error": "request_exception"}
    if not response.ok:
        return {"__error": f"http_{response.status}"}
    try:
        payload = response.json()
    except Exception:
        return {"__error": "invalid_json"}
    if not isinstance(payload, dict):
        return {"__error": "response_not_object"}
    return {
        "article_list": payload.get("article_list") if isinstance(payload.get("article_list"), list) else [],
        "base_ret": (payload.get("base_resp") or {}).get("ret") if isinstance(payload.get("base_resp"), dict) else None,
    }


def _write_report(
    output: Path,
    *,
    status: str,
    reason: str,
    records: list[dict[str, Any]],
    article_observations: list[dict[str, Any]] | None = None,
    article_collection_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "status": status,
        "reason": reason,
        "records": records,
        "article_observations": article_observations or [],
        "article_collection_audit": article_collection_audit or {},
    }
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
    collect_cmd.add_argument("--account-name", default="", help="Authorized account display name; required to emit article observations")
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
        result = collect(
            args.profile_dir,
            args.output,
            days=args.days,
            headless=not args.headed,
            state_file=args.state_file,
            account_name=args.account_name,
        )
    else:
        result = push_hermes(args.metrics_file, args.ssh_target, args.ssh_key, args.ssh_port, args.remote_project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
