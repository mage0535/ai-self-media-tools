"""Best-effort platform metric collectors.

The collector only records data it can actually read. Platforms that require
creator-center login exports are reported as action-needed instead of returning
fake zeros.
"""

from __future__ import annotations

import json
import os
import subprocess
import re
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


BACKEND_EXPORT_PLATFORMS = {
    "kuaishou",
    "shipinhao",
    "xiaohongshu",
    "douyin",
    "tiktok",
    "juejin",
    "zhihu",
}

LOGIN_STATE_PLATFORMS = {"douyin", "shipinhao", "xiaohongshu", "tiktok"}
MAX_REASONABLE_VISIBLE_METRIC = 100_000_000

BACKEND_BROWSER_TARGETS: dict[str, dict[str, Any]] = {
    "wechat": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN",
            "https://mp.weixin.qq.com/cgi-bin/appmsg?action=list_ex&begin=0&count=5&type=9&lang=zh_CN",
            "https://mp.weixin.qq.com/misc/appmsganalysis?action=all&lang=zh_CN",
            "https://mp.weixin.qq.com/cgi-bin/useranalysis?action=stat_user_summary&lang=zh_CN",
        ],
    },
    "kuaishou": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://cp.kuaishou.com/profile",
            "https://cp.kuaishou.com/article/manage/video?status=2&from=publish",
            "https://cp.kuaishou.com/article/manage/video",
        ],
    },
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
    "zhihu": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://www.zhihu.com/creator/analytics",
            "https://www.zhihu.com/creator/followers",
            "https://www.zhihu.com/creator/manage/creation",
            "https://www.zhihu.com/creator",
        ],
    },
    "juejin": {
        "proxy_env": "CN_PROXY",
        "urls": [
            "https://creator.juejin.cn/content",
            "https://juejin.cn/creator/content",
            "https://juejin.cn/user/center",
        ],
    },
}

PLATFORM_ALIASES = {
    "wxGzh": "wechat",
    "wxgzh": "wechat",
    "KWAI": "kuaishou",
    "kwai": "kuaishou",
    "wxSph": "shipinhao",
    "wxsph": "shipinhao",
    "xhs": "xiaohongshu",
}


def _fetch(url: str, timeout: int = 15, headers: dict[str, str] | None = None) -> str:
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; ContentPlatformMetrics/1.0)"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _http_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = None
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; ContentPlatformMetrics/1.0)"}
    request_headers.update(headers or {})
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method.upper())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace") or "{}")


def _to_int(value: Any) -> int:
    match = re.search(r"[\d,]+", str(value or ""))
    return int(match.group(0).replace(",", "")) if match else 0


def _platform(platform: str) -> str:
    raw = str(platform or "").strip()
    return PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(raw.casefold(), raw))


def _with_public_fallback(platform: str, result: dict[str, Any], config: dict[str, Any], fetcher: Callable[..., str]) -> dict[str, Any]:
    if result.get("status") in {"ok", "public_signal"}:
        return result
    public = _public_profile_signal(platform, config, fetcher)
    if public.get("status") != "missing_config":
        public["backend_status"] = result.get("status")
        public["backend_reason"] = result.get("reason", "")
        return public
    return result


def _public_profile_signal(platform: str, config: dict[str, Any], fetcher: Callable[..., str]) -> dict[str, Any]:
    urls = []
    for key in ("public_profile_url", "profile_url", "homepage_url", "public_url"):
        if config.get(key):
            urls.append(str(config[key]))
    if isinstance(config.get("public_urls"), list):
        urls.extend(str(item) for item in config["public_urls"] if str(item).strip())
    urls = list(dict.fromkeys(urls))
    if not urls:
        return {"status": "missing_config", "reason": "public_profile_url is not configured"}
    errors = []
    for url in urls:
        try:
            html = fetcher(url, timeout=20)
            metrics = _extract_public_metrics(html)
            if metrics:
                return {
                    "status": "public_signal",
                    "confidence": "low",
                    "reason": "creator backend unavailable; using public visible account signals",
                    "source_url": url,
                    "account_metrics": metrics,
                }
            errors.append("no visible metric labels")
        except Exception as exc:
            errors.append(str(exc)[:120])
    return {
        "status": "public_signal_unavailable",
        "confidence": "none",
        "reason": "; ".join(errors)[:300] or "public profile did not expose metrics",
    }


def _browser_backend_signal(platform: str, config: dict[str, Any]) -> dict[str, Any]:
    state_file = str(config.get("state_file") or config.get("cookie_file") or "").strip()
    if not state_file or not Path(state_file).is_file():
        return {"status": "missing_config", "reason": "state_file is not configured or missing"}
    state_file = _playwright_state_file(state_file)
    target = dict(BACKEND_BROWSER_TARGETS.get(platform, {}))
    if not target:
        return {"status": "missing_config", "reason": "no browser backend target registered"}
    if isinstance(config.get("backend_urls"), list):
        target["urls"] = [str(item) for item in config["backend_urls"] if str(item).strip()]
    proxy_env = str(config.get("proxy_env") or target.get("proxy_env") or "")
    proxy_url = os.environ.get(proxy_env, "") if proxy_env else ""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"status": "browser_unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    with sync_playwright() as pw:
        routes: list[tuple[str, str, bool]] = []
        if proxy_url:
            routes.append((proxy_env or "proxy", proxy_url, False))
        else:
            routes.append(("direct", "", False))
        diagnose_direct = bool(config.get("diagnose_direct_without_proxy")) or os.environ.get("CONTENT_PLATFORM_DIAGNOSE_DIRECT_BACKEND") == "1"
        if proxy_url and diagnose_direct:
            routes.append(("direct_diagnostic", "", True))
        route_errors: list[str] = []
        login_required = False
        for route_name, route_proxy, diagnostic_only in routes:
            result = _probe_browser_backend_route(pw, state_file, target, config, route_name, route_proxy, diagnostic_only)
            if result.get("status") == "backend_signal":
                if route_errors:
                    result["proxy_probe_errors"] = route_errors[-3:]
                return result
            if result.get("status") == "login_required_or_verification":
                login_required = True
            route_errors.append(f"{route_name}: {result.get('reason') or result.get('status')}")
    if login_required:
        return {"status": "login_required_or_verification", "reason": "creator backend requires login or verification"}
    return {"status": "backend_signal_unavailable", "reason": "; ".join(route_errors)[:300] or "backend metrics not visible"}


def _probe_browser_backend_route(
    pw: Any,
    state_file: str,
    target: dict[str, Any],
    config: dict[str, Any],
    route_name: str,
    proxy_url: str,
    diagnostic_only: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        browser = pw.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(storage_state=state_file, locale="zh-CN", viewport={"width": 1440, "height": 1200})
        try:
            for url in target.get("urls") or []:
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=int(config.get("timeout_ms") or 45000))
                    page.wait_for_timeout(int(config.get("settle_ms") or 8000))
                    text = page.locator("body").inner_text(timeout=8000)
                    lower = text.casefold()
                    if any(pattern in lower for pattern in ["登录", "扫码", "二维码", "验证", "login", "log in", "sign in", "sign up", "verify"]):
                        errors.append("login_required_or_verification")
                        continue
                    metrics = _extract_public_metrics(text)
                    if metrics:
                        metrics.setdefault("extra_metrics", {})
                        metrics["extra_metrics"].update(
                            {
                                "metric_source": "creator_backend_page",
                                "metric_confidence": "medium",
                                "backend_route": route_name,
                                "direct_diagnostic_only": bool(diagnostic_only),
                            }
                        )
                        return {
                            "status": "backend_signal",
                            "confidence": "medium",
                            "reason": "creator backend page exposed visible account/work metrics",
                            "account_metrics": metrics,
                            "source_url": page.url,
                        }
                    errors.append("loaded_but_metrics_not_visible")
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            context.close()
            browser.close()
    except Exception as exc:
        return {"status": "browser_probe_failed", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if any(item == "login_required_or_verification" for item in errors):
        return {"status": "login_required_or_verification", "reason": "creator backend requires login or verification"}
    return {"status": "backend_signal_unavailable", "reason": "; ".join(errors)[:300] or "backend metrics not visible"}


def _playwright_state_file(path: str) -> str:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and "cookies" in data:
        return path
    if isinstance(data, list):
        cookies = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cookie = {
                "name": item.get("name", ""),
                "value": item.get("value", ""),
                "domain": item.get("domain", ""),
                "path": item.get("path") or "/",
                "httpOnly": bool(item.get("httpOnly", False)),
                "secure": bool(item.get("secure", False)),
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
        tmp = Path(tempfile.gettempdir()) / f"content_platform_state_{abs(hash(path))}.json"
        tmp.write_text(json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False), encoding="utf-8")
        return str(tmp)
    return path


def _extract_public_metrics(html: str) -> dict[str, Any]:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    metrics: dict[str, Any] = {}
    label_map = {
        "followers": ["累计关注人数", "总用户数", "净增粉丝量", "关注者总数", "关注者", "订阅者", "粉丝", "followers", "subscribers", "fans"],
        "following": ["正在关注", "关注", "following"],
        "works": ["作品", "内容", "文章", "视频", "笔记", "notes", "posts", "videos", "works"],
        "likes": ["获赞", "点赞量", "点赞", "赞同总量", "赞同", "赞", "喜欢总量", "喜欢", "likes"],
        "views": ["昨日阅读", "阅读总量", "播放量", "播放总量", "播放", "观看", "浏览", "阅读", "展现", "views", "plays", "reads", "impressions"],
        "saves": ["收藏", "favorites", "favorite", "saves", "bookmarks"],
        "comments": ["评论总量", "评论量", "评论", "comments", "replies"],
        "shares": ["昨日分享", "分享总量", "分享量", "分享", "转发总数", "转发", "shares", "reposts"],
    }
    for target, labels in label_map.items():
        for label in labels:
            value = _metric_after_label(text, label)
            if value is not None:
                if 0 <= value <= MAX_REASONABLE_VISIBLE_METRIC:
                    metrics[target] = value
                break
    if not any(int(value or 0) > 0 for key, value in metrics.items() if isinstance(value, (int, float))):
        return {}
    if metrics:
        title = _extract_title(html)
        if title:
            metrics["title"] = title
        metrics["extra_metrics"] = {
            "metric_source": "public_page",
            "metric_confidence": "low",
        }
    return metrics


def _metric_after_label(text: str, label: str) -> int | None:
    escaped = re.escape(label)
    match = re.search(rf"{escaped}\s*[:：]?\s*([0-9][0-9,\.]*\s*[万亿kKmM]?)", text, re.IGNORECASE)
    if match:
        return _parse_compact_number(match.group(1))
    marker = re.search(escaped, text, re.IGNORECASE)
    if marker:
        segment = _metric_segment(text[marker.end() : marker.end() + 80])
        raw_numbers = re.findall(r"([+-]?\d[\d,\.]*\s*[万亿kKmM]?)", segment)
        if raw_numbers:
            values = [_parse_compact_number(raw.lstrip("+")) for raw in raw_numbers]
            if "昨日" in segment[:20] and len(values) > 1:
                return values[-1]
            return values[0]
    match = re.search(rf"([0-9][0-9,\.]*\s*[万亿kKmM]?)\s*(?:个|条|篇)?\s*{escaped}", text, re.IGNORECASE)
    if match:
        return _parse_compact_number(match.group(1))
    return None


def _metric_segment(segment: str) -> str:
    boundaries = [
        "播放量",
        "播放总量",
        "阅读总量",
        "点赞量",
        "赞同总量",
        "评论量",
        "评论总量",
        "收藏总量",
        "分享量",
        "分享总量",
        "转发总数",
        "净增粉丝量",
        "关注者总数",
        "完播率",
    ]
    cuts = [idx for label in boundaries if (idx := segment.find(label)) > 0]
    if cuts:
        return segment[: min(cuts)]
    return segment[:30]


def _parse_compact_number(value: Any) -> int:
    text = str(value or "").strip().replace(",", "")
    multiplier = 1
    if text.lower().endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.lower().endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    try:
        return int(float(text.strip()) * multiplier)
    except ValueError:
        return 0

def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:120]


def _youtube(channel_url: str, fetcher: Callable[..., str]) -> dict[str, Any]:
    if not channel_url:
        return {"status": "missing_config", "reason": "youtube channel_url is required"}
    html = fetcher(channel_url, timeout=20)
    metrics = {}
    for key, field in [
        ("subscriberCountText", "subscribers"),
        ("videoCountText", "videos"),
        ("viewCountText", "views"),
    ]:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', html)
        if match:
            metrics[field] = _to_int(match.group(1))
            metrics[f"{field}_raw"] = match.group(1)
    if not metrics:
        return {"status": "unavailable", "reason": "youtube public page did not expose account metrics"}
    return {"status": "ok", "account_metrics": metrics}


def _bilibili(config: dict[str, Any], fetcher: Callable[..., str]) -> dict[str, Any]:
    cookie_file = str(config.get("cookie_file") or "").strip()
    headers: dict[str, str] = {}
    mid = str(config.get("mid") or config.get("uid") or "").strip()
    if cookie_file:
        cookie_result = _bilibili_cookie_header(cookie_file)
        if cookie_result.get("status") != "ok":
            return cookie_result
        headers["Cookie"] = str(cookie_result["cookie_header"])
        nav_raw = fetcher("https://api.bilibili.com/x/web-interface/nav", timeout=20, headers=headers)
        try:
            nav = json.loads(nav_raw)
        except json.JSONDecodeError:
            return {"status": "unavailable", "reason": "bilibili nav API did not return JSON"}
        data = nav.get("data") or {}
        if nav.get("code") != 0 or not data.get("isLogin"):
            return {"status": "login_required", "reason": "bilibili cookie is missing, expired, or not logged in"}
        mid = str(data.get("mid") or mid or "")
    if not mid:
        return {"status": "missing_config", "reason": "bilibili mid is required"}
    if headers:
        raw = fetcher(f"https://api.bilibili.com/x/web-interface/card?mid={mid}", timeout=20, headers=headers)
    else:
        raw = fetcher(f"https://api.bilibili.com/x/web-interface/card?mid={mid}", timeout=20)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "bilibili API did not return JSON"}
    if payload.get("code") != 0:
        return {"status": "unavailable", "reason": f"bilibili API error: {payload.get('message', '')}"}
    data = payload.get("data") or {}
    card = data.get("card") or {}
    return {
        "status": "ok",
        "account_metrics": {
            "name": card.get("name", ""),
            "fans": int(card.get("fans") or 0),
            "following": int(card.get("attention") or 0),
            "videos": int(data.get("archive_count") or card.get("videos") or 0),
            "likes": int(data.get("like_num") or card.get("likes") or 0),
        },
    }


def _tiktok_api_metrics(config: dict[str, Any], http_json: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    api_url = str(config.get("api_url") or config.get("analytics_api_url") or os.environ.get("TIKTOK_METRICS_API_URL", "")).strip()
    if not api_url:
        return {"status": "missing_config", "reason": "tiktok api_url is not configured"}
    token_env = str(config.get("api_token_env") or "TIKTOK_METRICS_API_TOKEN").strip()
    token = os.environ.get(token_env, "")
    headers = dict(config.get("api_headers") or {})
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
    try:
        data = http_json(str(config.get("api_method") or "GET"), api_url, headers=headers, timeout=int(config.get("api_timeout") or 30))
    except Exception as exc:
        return {"status": "api_unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}
    metrics = _normalize_tiktok_api_metrics(data)
    if not metrics:
        return {"status": "api_unavailable", "reason": "tiktok metrics API returned no recognized growth metrics"}
    metrics.setdefault("extra_metrics", {})
    metrics["extra_metrics"].update({"metric_source": "tiktok_metrics_api", "metric_confidence": "high"})
    return {"status": "ok", "account_metrics": metrics, "source_url": api_url}


def _normalize_tiktok_api_metrics(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    candidates = [data]
    for key in ("data", "metrics", "account_metrics", "analytics", "result"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    metrics: dict[str, Any] = {}
    aliases = {
        "views": ("views", "video_views", "play_count", "plays", "total_views", "organic_video_views"),
        "likes": ("likes", "like_count", "total_likes"),
        "comments": ("comments", "comment_count", "total_comments"),
        "shares": ("shares", "share_count", "total_shares"),
        "saves": ("saves", "favorites", "favorite_count", "collect_count"),
        "followers": ("followers", "follower_count", "fans", "total_followers"),
        "completion_rate": ("completion_rate", "avg_completion_rate"),
        "three_second_view_rate": ("three_second_view_rate", "three_sec_view_rate"),
        "avg_watch_seconds": ("avg_watch_seconds", "average_watch_time", "avg_watch_time_seconds"),
    }
    for source in candidates:
        for target, keys in aliases.items():
            for key in keys:
                if key in source:
                    value = float(source.get(key) or 0) if target in {"completion_rate", "three_second_view_rate", "avg_watch_seconds"} else _to_int(source.get(key))
                    metrics[target] = float(value) if target in {"completion_rate", "three_second_view_rate", "avg_watch_seconds"} else int(value)
                    break
    videos = data.get("videos") or data.get("items") or data.get("posts")
    if isinstance(videos, list):
        totals = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0}
        for item in videos:
            if not isinstance(item, dict):
                continue
            item_metrics = _normalize_tiktok_api_metrics(item)
            for key in totals:
                totals[key] += int(item_metrics.get(key, 0) or 0)
        for key, value in totals.items():
            if value:
                metrics[key] = int(metrics.get(key, 0) or 0) + value
        metrics.setdefault("extra_metrics", {})["video_count"] = len(videos)
    return metrics


def _metrics_file_signal(platform: str, config: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(config.get("metrics_file") or config.get("analytics_file") or "").strip())
    if not path:
        return {"status": "missing_config", "reason": "metrics_file is not configured"}
    if not path.is_file():
        return {"status": "metrics_file_missing", "reason": f"metrics_file not found for {platform}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "metrics_file_invalid", "reason": f"metrics_file is not JSON for {platform}"}
    rows = data.get("videos") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {"status": "metrics_file_invalid", "reason": "metrics_file must contain a list or videos list"}
    metrics = {
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
        "followers": 0,
        "works": 0,
        "extra_metrics": {"metric_source": "metrics_file", "metric_confidence": "medium", "metrics_file": str(path)},
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics["views"] += _first_int(row, "views", "播放", "阅读", "read_count", "play_count")
        metrics["likes"] += _first_int(row, "likes", "喜欢", "点赞", "获赞")
        metrics["comments"] += _first_int(row, "comments", "评论")
        metrics["shares"] += _first_int(row, "shares", "分享", "转发")
        metrics["saves"] += _first_int(row, "saves", "收藏")
        metrics["followers"] += _first_int(row, "follows", "followers", "关注", "新增关注")
        metrics["works"] += 1
    if not any(int(metrics.get(key, 0)) for key in ("views", "likes", "comments", "shares", "saves", "followers", "works")):
        return {"status": "metrics_file_empty", "reason": "metrics_file had no numeric metrics"}
    return {"status": "ok", "account_metrics": metrics}


def _first_int(row: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key in row:
            try:
                return int(float(str(row.get(key) or 0).replace(",", "")))
            except ValueError:
                return 0
    return 0


def _bilibili_cookie_header(cookie_file: str) -> dict[str, Any]:
    path = Path(cookie_file)
    if not path.is_file():
        return {"status": "login_required", "reason": "bilibili cookie_file is missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "failed", "reason": f"bilibili cookie_file cannot be read: {exc}"[:300]}
    cookies: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
        cookies = payload["cookies"]
    elif isinstance(payload, dict) and isinstance(payload.get("cookie_info"), dict):
        cookies = [{"name": key, "value": value} for key, value in payload["cookie_info"].items()]
    elif isinstance(payload, dict):
        cookies = [{"name": key, "value": value} for key, value in payload.items()]
    elif isinstance(payload, list):
        cookies = payload
    parts = [f"{item.get('name')}={item.get('value')}" for item in cookies if isinstance(item, dict) and item.get("name") and item.get("value")]
    if not parts:
        return {"status": "login_required", "reason": "bilibili cookie_file has no usable cookie values"}
    return {"status": "ok", "cookie_header": "; ".join(parts)}


def _wechat_datacube(config: dict[str, Any], http_json: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    private_env = _load_env_file(str(config.get("env_file") or ""))
    app_id = str(config.get("app_id") or private_env.get("WECHAT_APP_ID") or private_env.get("WECHAT_APPID") or os.environ.get("WECHAT_APP_ID") or os.environ.get("WECHAT_APPID") or "").strip()
    app_secret = str(config.get("app_secret") or private_env.get("WECHAT_APP_SECRET") or private_env.get("WECHAT_SECRET") or os.environ.get("WECHAT_APP_SECRET") or os.environ.get("WECHAT_SECRET") or "").strip()
    if not app_id or not app_secret:
        return {
            "status": "backend_export_required",
            "reason": "wechat statistics require WECHAT_APP_ID and WECHAT_APP_SECRET, or backend export from mp.weixin.qq.com",
            "next_action": "configure official account statistics API credentials or export backend metrics then run performance-import",
        }
    token = http_json(
        "GET",
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=30,
    )
    access_token = token.get("access_token")
    if not access_token:
        return {"status": "failed", "reason": "wechat token request failed", "wechat_error": _wechat_error(token)}
    date_range = config.get("date_range") if isinstance(config.get("date_range"), dict) else {}
    begin_date = str(date_range.get("begin_date") or config.get("begin_date") or "")
    end_date = str(date_range.get("end_date") or config.get("end_date") or "")
    if not begin_date or not end_date:
        # WeChat Datacube generally requires completed dates. Callers can override for exact windows.
        from datetime import timedelta

        end = datetime.now(timezone.utc).date() - timedelta(days=1)
        begin = end - timedelta(days=6)
        begin_date, end_date = str(begin), str(end)
    payload = {"begin_date": begin_date, "end_date": end_date}
    endpoints = {
        "user_summary": "https://api.weixin.qq.com/datacube/getusersummary",
        "user_cumulate": "https://api.weixin.qq.com/datacube/getusercumulate",
        "article_summary": "https://api.weixin.qq.com/datacube/getarticlesummary",
        "article_total": "https://api.weixin.qq.com/datacube/getarticletotal",
    }
    metrics: dict[str, Any] = {}
    permission_blocked = False
    for name, url in endpoints.items():
        data = http_json("POST", url, params={"access_token": access_token}, data=payload, timeout=45)
        if isinstance(data.get("list"), list):
            metrics[name] = {"status": "ok", "count": len(data["list"]), "last": data["list"][-3:]}
        else:
            error = _wechat_error(data)
            metrics[name] = {"status": "error", **error}
            if error.get("errcode") == 48001:
                permission_blocked = True
    if permission_blocked and not any(item.get("status") == "ok" for item in metrics.values()):
        return {
            "status": "api_permission_blocked",
            "reason": "wechat Datacube API returned 48001 api unauthorized",
            "next_action": "open/authorize the official account statistics interface, or collect metrics from mp.weixin.qq.com backend export and import them with performance-import",
            "date_range": payload,
            "metrics": metrics,
        }
    return {"status": "ok", "date_range": payload, "metrics": metrics}


def _wechat_error(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data.get(key) for key in ["errcode", "errmsg"] if key in data}


def _wechat_backend_cookie_metrics(config: dict[str, Any]) -> dict[str, Any]:
    state_file = str(config.get("state_file") or config.get("cookie_file") or "").strip()
    if not state_file:
        return {"status": "missing_config", "reason": "wechat backend state_file is not configured"}
    try:
        from scripts.wechat_mp_backend_collector import collect
    except Exception as exc:
        return {"status": "browser_unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = collect(
                Path(str(config.get("profile_dir") or Path(tmp) / "wechat_profile")),
                Path(tmp) / "wechat_backend_metrics.json",
                days=int(config.get("days") or 30),
                headless=True,
                state_file=Path(state_file),
            )
        except SystemExit as exc:
            return {"status": "browser_unavailable", "reason": str(exc)[:160]}
        except Exception as exc:
            return {"status": "backend_signal_unavailable", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    if result.get("status") != "ok" or not result.get("records"):
        return {
            "status": str(result.get("status") or "backend_signal_unavailable"),
            "reason": str(result.get("reason") or "wechat backend cookie collector did not return records")[:300],
        }
    record = result["records"][0]
    extra = dict(record.get("metrics") or {})
    extra.update({"metric_source": "wechat_backend_cookie", "metric_confidence": "medium"})
    return {
        "status": "backend_signal",
        "confidence": "medium",
        "reason": "mp.weixin.qq.com backend cookie exposed visible metrics",
        "account_metrics": {
            "views": int(record.get("views", 0) or 0),
            "shares": int(record.get("shares", 0) or 0),
            "followers": int(record.get("follows", 0) or 0),
            "extra_metrics": extra,
        },
        "source_url": "mp.weixin.qq.com backend",
    }


def _load_env_file(path_value: str) -> dict[str, str]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _login_state_status(platform: str, config: dict[str, Any]) -> dict[str, Any]:
    state_file = str(config.get("state_file") or config.get("cookie_file") or "").strip()
    if not state_file:
        return {
            "status": "backend_export_required",
            "reason": f"{platform} metrics require an authenticated creator-center browser state or manual backend export",
            "next_action": "refresh persistent login state, run a platform-specific browser collector, then import metrics",
        }
    if not Path(state_file).is_file():
        return {
            "status": "login_required",
            "reason": f"{platform} state_file is missing or has been cleaned",
            "next_action": "refresh platform login state before collecting metrics",
        }
    return {
        "status": "browser_probe_required",
        "reason": f"{platform} has a state file, but metrics require a platform-specific browser probe to verify login and scrape backend data",
        "state_file_present": True,
        "next_action": "run Hermes browser collector with the configured state_file and save evidence screenshots",
    }


def _backend_export_status(platform: str) -> dict[str, Any]:
    return {
        "status": "backend_export_required",
        "reason": "creator-center metrics require authenticated backend export or a platform-specific browser collector",
        "next_action": "export CSV then run performance-import; see docs/performance-metrics-import.md",
    }


def collect_platform_metrics(
    platforms: list[str],
    config: dict[str, Any] | None = None,
    *,
    output: str | Path | None = None,
    fetcher: Callable[..., str] = _fetch,
    http_json: Callable[..., dict[str, Any]] = _http_json,
) -> dict[str, Any]:
    cfg = config or {}
    report = {
        "status": "ok",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": {},
    }
    for requested in platforms:
        platform = _platform(requested)
        pcfg = cfg.get(platform, {}) if isinstance(cfg.get(platform, {}), dict) else {}
        try:
            if platform == "tiktok" and (pcfg.get("api_url") or pcfg.get("analytics_api_url") or os.environ.get("TIKTOK_METRICS_API_URL")):
                result = _tiktok_api_metrics(pcfg, http_json)
            elif pcfg.get("metrics_file") or pcfg.get("analytics_file"):
                result = _metrics_file_signal(platform, pcfg)
            elif platform == "youtube":
                result = _youtube(str(pcfg.get("channel_url") or pcfg.get("url") or ""), fetcher)
            elif platform == "bilibili":
                result = _bilibili(pcfg, fetcher)
            elif platform == "wechat":
                if pcfg.get("datacube") or pcfg.get("app_id") or os.environ.get("WECHAT_APP_ID") or os.environ.get("WECHAT_APPID"):
                    result = _wechat_datacube(pcfg, http_json)
                    if result.get("status") != "ok" and (pcfg.get("state_file") or pcfg.get("cookie_file") or pcfg.get("backend_urls")):
                        backend_result = _wechat_backend_cookie_metrics(pcfg)
                        if backend_result.get("status") != "backend_signal":
                            backend_result = _browser_backend_signal(platform, pcfg)
                        if backend_result.get("status") == "backend_signal":
                            backend_result["datacube_status"] = result.get("status")
                            backend_result["datacube_reason"] = result.get("reason", "")
                            result = backend_result
                        else:
                            result["backend_probe_status"] = backend_result.get("status")
                            result["backend_probe_reason"] = backend_result.get("reason", "")
                            result["next_action"] = "refresh mp.weixin.qq.com browser state or export backend metrics then run performance-import"
                else:
                    result = _wechat_backend_cookie_metrics(pcfg) if (pcfg.get("state_file") or pcfg.get("cookie_file")) else _browser_backend_signal(platform, pcfg)
                    if result.get("status") != "backend_signal" and (pcfg.get("state_file") or pcfg.get("cookie_file")):
                        result = _browser_backend_signal(platform, pcfg)
                    if result.get("status") == "missing_config":
                        result = {
                            "status": "backend_export_required",
                            "reason": "wechat metrics require Datacube API permission, mp.weixin.qq.com browser state, or backend export",
                            "next_action": "enable Datacube API, configure a WeChat backend state_file, or export backend metrics then run performance-import",
                        }
            elif platform in LOGIN_STATE_PLATFORMS:
                result = _browser_backend_signal(platform, pcfg)
                if result.get("status") == "missing_config":
                    result = _login_state_status(platform, pcfg)
            elif platform in BACKEND_EXPORT_PLATFORMS:
                result = _browser_backend_signal(platform, pcfg)
                if result.get("status") == "missing_config":
                    result = _backend_export_status(platform)
            else:
                result = {"status": "unsupported", "reason": "no collector registered"}
        except Exception as exc:
            result = {"status": "failed", "reason": str(exc)[:300]}
        result = _with_public_fallback(platform, result, pcfg, fetcher)
        report["platforms"][platform] = result
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def collect_with_hermes_platform_scraper(
    platforms: list[str],
    *,
    script_path: str | Path = "",
    output: str | Path | None = None,
    runner: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> dict[str, Any]:
    runner = runner or _run_command
    script = Path(script_path or os.environ.get("HERMES_PLATFORM_SCRAPER", ""))
    if not script:
        return {
            "status": "unavailable",
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "hermes_platform_scraper",
            "platforms": {str(_platform(platform)): {"status": "missing_config", "reason": "HERMES_PLATFORM_SCRAPER is not configured"} for platform in platforms},
        }
    code, stdout, stderr = runner(["python3", str(script), "--json"])
    report = {
        "status": "ok" if code == 0 else "failed",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "hermes_platform_scraper",
        "platforms": {},
    }
    if code != 0:
        report["error"] = (stderr or stdout)[:500]
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
        report["status"] = "failed"
        report["error"] = "Hermes platform scraper did not return JSON"
    platform_payload = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else payload
    for requested in platforms:
        platform = _platform(requested)
        item = platform_payload.get(platform, {}) if isinstance(platform_payload, dict) else {}
        if platform == "twitter" and not item:
            item = platform_payload.get("x", {}) if isinstance(platform_payload, dict) else {}
        if isinstance(item, dict) and item:
            if "account_metrics" in item:
                report["platforms"][platform] = item
            else:
                report["platforms"][platform] = {"status": "ok", "account_metrics": item}
        else:
            report["platforms"][platform] = {"status": "unavailable", "reason": "not returned by Hermes platform scraper"}
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _run_command(command: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr
