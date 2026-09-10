from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121 Safari/537.36"

STRONG_EVIDENCE = {
    "strong_logged_search_result",
    "strong_public_shipin_related",
    "strong_public_transcript",
    "strong_public_detail",
    "strong_cached_native_search",
    "strong_public_wechat_search",
}

DOUYIN_AI_SPECIFIC = ("ai工具", "ai agent", "智能体", "大模型", "工作流", "自动化", "效率工具", "人工智能工具")
DOUYIN_PET_SPECIFIC = ("猫", "狗", "宠物", "萌宠", "铲屎官")


def default_platform_queries(platform: str) -> list[str]:
    from .platform_intelligence_registry import platform_queries

    normalized = str(platform or "").casefold().strip()
    aliases = {"douyin": "douyin_ai", "x": "twitter", "rednote": "xiaohongshu"}
    return platform_queries(normalized) or platform_queries(aliases.get(normalized, "")) or ["AI工具 工作流"]


def filter_douyin_official_board(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    normalized = str(platform or "").casefold().strip()
    tokens = DOUYIN_PET_SPECIFIC if normalized == "douyin_pet" else DOUYIN_AI_SPECIFIC
    return [dict(row) for row in rows if any(token in str(row.get("title") or "").casefold() for token in tokens)]


def build_douyin_official_row(rows: list[dict[str, Any]], platform: str, *, captured_at: datetime | None = None) -> dict[str, Any]:
    current = captured_at or datetime.now(timezone.utc)
    selected = filter_douyin_official_board(rows, platform)
    if not selected:
        return {}
    snapshot_hash = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "platform": str(platform).casefold(),
        "status": "verified",
        "signal_type": "hot_list",
        "evidence_type": "official_keyword",
        "signals": [str(row.get("title") or "") for row in selected],
        "signal_details": [{"title": row.get("title"), "heat": row.get("points", 0), "rank": row.get("rank", 0)} for row in selected],
        "official_url": "https://www.douyin.com/aweme/v1/hot/search/list/",
        "final_url": "https://www.douyin.com/aweme/v1/hot/search/list/",
        "captured_at": current.astimezone(timezone.utc).isoformat(),
        "expires_at": (current.astimezone(timezone.utc) + timedelta(hours=6)).isoformat(),
        "evidence_sha256": snapshot_hash,
        "raw_snapshot_sha256": snapshot_hash,
        "collector": "douyin_official_hot_board",
        "native_verified": False,
    }


def resolve_logged_search_state(
    platform: str,
    output_dir: str | Path,
    *,
    cookie_dir: str = "",
) -> dict[str, Any]:
    """Resolve a valid private cookie file and materialize Playwright state."""
    from .auth_registry import cookie_file_status, resolve_cookie_file

    source = resolve_cookie_file(platform, cookie_dir=cookie_dir)
    status = cookie_file_status(source, platform)
    if not status.get("valid"):
        return {"status": "unavailable", "reason": "valid_private_cookie_state_not_found", "state_file": ""}
    if status.get("format") == "playwright_storage_state":
        state = source
    else:
        state = Path(output_dir) / f"{str(platform).casefold().strip()}_playwright_state.json"
        write_playwright_state(source, state)
        try:
            state.chmod(0o600)
        except OSError:
            pass
    return {"status": "ready", "reason": "", "state_file": str(state), "source_format": str(status.get("format") or "")}


def strip_markup(value: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", str(value or ""), flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_browser_cookies(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert extension-exported cookies into Playwright storage_state."""
    normalized = []
    for cookie in cookies:
        if not all(cookie.get(key) for key in ("name", "value", "domain")):
            continue
        row: dict[str, Any] = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path") or "/",
            "httpOnly": bool(cookie.get("httpOnly", False)),
            "secure": bool(cookie.get("secure", False)),
        }
        if "expirationDate" in cookie:
            row["expires"] = int(float(cookie["expirationDate"]))
        elif "expires" in cookie:
            row["expires"] = int(float(cookie["expires"]))
        same_site = str(cookie.get("sameSite") or "").lower()
        if same_site == "strict":
            row["sameSite"] = "Strict"
        elif same_site == "lax":
            row["sameSite"] = "Lax"
        elif same_site in {"none", "no_restriction"}:
            row["sameSite"] = "None"
        normalized.append(row)
    return {"cookies": normalized, "origins": []}


def write_playwright_state(cookie_file: str | Path, output: str | Path) -> Path:
    source = Path(cookie_file)
    data = json.loads(source.read_text(encoding="utf-8"))
    cookies = data.get("cookies") if isinstance(data, dict) else data
    if not isinstance(cookies, list):
        raise ValueError(f"unsupported cookie format: {source}")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalize_browser_cookies(cookies), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def analyze_work(title: str, body: str = "") -> dict[str, list[str]]:
    full = f"{title} {body}".casefold()
    hooks: list[str] = []
    structures: list[str] = []
    styles: list[str] = []
    display: list[str] = []
    if re.search(r"\d+", title):
        hooks.append("数字/规模")
    if any(token in title for token in ("别再", "不要", "避坑", "裸用", "反超", "到底", "过时", "破防", "省", "赚")):
        hooks.append("冲突/收益")
    if any(token in full for token in ("claude", "codex", "mcp", "skills", "agent", "n8n", "workflow", "ai工具", "工作流", "自动化")):
        hooks.append("具体工具")
    if any(token in title for token in ("教程", "指南", "实战", "保姆级", "安装", "配置", "怎么", "如何", "学会", "搭建")):
        hooks.append("教程/可复现")
    if any(token in full for token in ("步骤", "安装", "配置", "清单", "一键", "命令", "代码", "实例")):
        structures.append("步骤/清单")
    if any(token in full for token in ("截图", "见下图", "演示", "实测", "运行", "效果", "案例")):
        structures.append("证据/演示")
    if any(token in full for token in ("对比", " vs ", "选哪个", "区别")):
        structures.append("对比评测")
    if any(token in full for token in ("保姆级", "零基础", "新手", "小白")):
        styles.append("低门槛教学")
    if any(token in full for token in ("亲测", "实测", "踩坑", "效果", "完整")):
        styles.append("实测可信")
    if any(token in full for token in ("收藏", "清单", "完整", "大全", "必学")):
        styles.append("收藏型")
    if any(token in full for token in ("图", "视频", "画面", "镜头", "截图", "演示", "工作流")):
        display.append("图解/演示")
    return {
        "hook_types": hooks or ["信息钩子"],
        "structure_types": structures or ["结构待补"],
        "copy_style": styles or ["信息说明"],
        "display_style": display or ["待抽帧确认"],
    }


def _work(platform: str, source: str, query: str, title: str, **kwargs: Any) -> dict[str, Any]:
    item = {
        "platform": platform,
        "source": source,
        "query": query,
        "title": strip_markup(title),
        "evidence_strength": kwargs.pop("evidence_strength"),
        "captured_at": kwargs.pop("captured_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "collector": kwargs.pop("collector", source),
    }
    item.update({key: value for key, value in kwargs.items() if value not in (None, "")})
    item["analysis"] = analyze_work(item["title"], str(item.get("excerpt") or ""))
    return item


def parse_sogou_wechat_html(raw_html: str, *, query: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for block in re.findall(r"<li[^>]*>.*?</li>", raw_html, flags=re.S | re.I):
        if "<h3" not in block:
            continue
        title_match = re.search(r"<h3.*?</h3>", block, flags=re.S | re.I)
        title = strip_markup(title_match.group(0) if title_match else "")
        if not title:
            continue
        href_match = re.search(r"href=['\"]([^'\"]+)['\"]", block)
        desc_match = re.search(r"<p[^>]*class=['\"][^'\"]*txt-info[^'\"]*['\"].*?</p>", block, flags=re.S | re.I)
        account_match = re.search(r"<a[^>]*account_name[^>]*>.*?</a>", block, flags=re.S | re.I)
        rows.append(
            _work(
                "wechat",
                "sogou_weixin",
                query,
                title,
                url=urllib.parse.urljoin("https://weixin.sogou.com", html.unescape(href_match.group(1))) if href_match else "",
                author=strip_markup(account_match.group(0)) if account_match else "",
                excerpt=strip_markup(desc_match.group(0)) if desc_match else "",
                evidence_strength="strong_public_wechat_search",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _is_content_url(platform: str, href: str) -> bool:
    parsed = urllib.parse.urlparse(str(href or ""))
    host = (parsed.hostname or "").casefold()
    path = parsed.path or "/"
    contracts = {
        "bilibili": (("bilibili.com",), ("/video/", "/opus/", "/read/cv")),
        "douyin": (("douyin.com",), ("/video/",)),
        "douyin_ai": (("douyin.com",), ("/video/",)),
        "douyin_pet": (("douyin.com",), ("/video/",)),
        "juejin": (("juejin.cn",), ("/post/",)),
        "kuaishou": (("kuaishou.com",), ("/short-video/",)),
        "tiktok": (("tiktok.com",), ("/video/",)),
        "twitter": (("x.com", "twitter.com"), ("/status/",)),
        "xiaohongshu": (("xiaohongshu.com",), ("/explore/", "/discovery/item/", "/search_result/")),
        "youtube": (("youtube.com", "youtu.be"), ("/watch", "/shorts/")),
        "zhihu": (("zhihu.com",), ("/question/", "/p/")),
    }
    hosts, paths = contracts.get(platform, ((), ()))
    return bool(hosts and any(host == suffix or host.endswith("." + suffix) for suffix in hosts) and any(token in path for token in paths))


def _matching_anchor(title: str, anchors: list[dict[str, str]] | None, *, platform: str) -> str:
    wanted = strip_markup(title).casefold()
    for anchor in anchors or []:
        label = strip_markup(str(anchor.get("text") or "")).casefold()
        href = str(anchor.get("href") or "").strip()
        if label and _is_content_url(platform, href) and (wanted in label or label in wanted):
            return href
    return ""


def parse_xiaohongshu_search_text(text: str, *, query: str, limit: int = 12, anchors: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    skip = {"首页", "点点", "ai", "RED", "直播", "发布", "通知", "消息", "我", "全部", "图文", "视频", "用户", "筛选", "综合", "大家都在搜", "活动"}
    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(lines) - 2:
        title, author, date = lines[index], lines[index + 1], lines[index + 2]
        metric = lines[index + 3] if index + 3 < len(lines) and re.fullmatch(r"\d+(\.\d+K|K|M|万)?", lines[index + 3]) else ""
        if (
            title not in skip
            and len(title) >= 6
            and "ICP备" not in title
            and re.search(r"(\d{2}-\d{2}|昨天|今天|小时前|天前|202\d|\d+小时前|\d+天前)", date)
        ):
            rows.append(
                _work(
                    "xiaohongshu",
                    "xiaohongshu_logged_search",
                    query,
                    title,
                    author=author,
                    date=date,
                    engagement=metric,
                    url=_matching_anchor(title, anchors, platform="xiaohongshu"),
                    evidence_strength="strong_logged_search_result",
                )
            )
            index += 4 if metric else 3
        else:
            index += 1
        if len(rows) >= limit:
            break
    return rows


def parse_tiktok_search_text(text: str, *, query: str, limit: int = 12) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r"\d+(\.\d+K|K|M)?", line) or index + 3 >= len(lines):
            continue
        title, author, date = lines[index + 1], lines[index + 2], lines[index + 3]
        title_l = title.casefold()
        if len(title) > 15 and any(token in title_l for token in ("ai", "workflow", "automation", "claude", "n8n", "agent")):
            rows.append(
                _work(
                    "tiktok",
                    "tiktok_logged_search",
                    query,
                    title,
                    author=author,
                    date=date,
                    engagement=line,
                    evidence_strength="strong_logged_search_result",
                )
            )
        if len(rows) >= limit:
            break
    return rows


def _looks_like_content_line(line: str, query: str) -> bool:
    text = str(line or "").strip()
    if len(text) < 8 or len(text) > 120:
        return False
    blocked = (
        "登录",
        "验证码",
        "服务器出错",
        "刷新重试",
        "隐私",
        "用户协议",
        "关注",
        "推荐",
        "首页",
        "消息",
        "all rights reserved",
        "备案",
        "公网安备",
        "举报",
        "营业执照",
        "许可证",
        "快币充值",
        "返回旧版",
    )
    lowered = text.casefold()
    if any(token in text or token in lowered for token in blocked):
        return False
    query_tokens = [token for token in re.split(r"\s+", str(query or "").casefold()) if len(token) >= 2]
    lane_tokens = ("ai", "claude", "codex", "agent", "工作流", "自动化", "效率", "猫", "狗", "宠物", "萌宠", "治愈")
    return any(token in lowered for token in query_tokens) or any(token in lowered for token in lane_tokens)


def _nearby_metric(lines: list[str], title: str) -> str:
    try:
        index = lines.index(title)
    except ValueError:
        return ""
    for line in lines[index + 1:index + 7]:
        normalized = line.strip().lstrip("·• ")
        if re.fullmatch(r"20\d{2}(?:[-/.]\d{1,2})?(?:[-/.]\d{1,2})?", normalized):
            continue
        match = re.fullmatch(
            r"(?:赞同|点赞|赞|播放|观看|喜欢|收藏|评论|获赞)?\s*(\d+(?:\.\d+)?(?:K|M|万)?)\s*(?:赞同|点赞|赞|播放|观看|喜欢|收藏|评论|次)?",
            normalized,
            re.I,
        )
        if match and _metric_number(match.group(1)) > 0:
            return match.group(1)
    return ""


def parse_platform_search_evidence(
    text: str,
    *,
    anchors: list[dict[str, str]],
    platform: str,
    query: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build strong rows only from real content links with visible metrics."""
    lowered = str(text or "").casefold()
    if any(token in lowered for token in ("服务器出现问题", "服务器出错", "请求过于频繁", "captcha", "验证码")):
        return []
    lines = [strip_markup(line) for line in str(text or "").splitlines() if strip_markup(line)]
    blocked_titles = {"ai works", "首页", "综合", "视频", "用户", "热榜", "创作中心", "内容发现"}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_urls: set[str] = set()
    for anchor in anchors:
        title = strip_markup(str(anchor.get("text") or ""))
        href = str(anchor.get("href") or "").strip()
        key = title.casefold()
        if key in seen or key in blocked_titles or not href.startswith(("http://", "https://")):
            continue
        if not _is_content_url(platform, href):
            continue
        canonical_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(href)[:3], "", ""))
        if canonical_url in seen_urls:
            continue
        if not _looks_like_content_line(title, query):
            continue
        metric = _nearby_metric(lines, title)
        if _metric_number(metric) <= 0:
            continue
        seen.add(key)
        seen_urls.add(canonical_url)
        rows.append(_work(platform, f"{platform}_logged_search", query, title, url=href, engagement=metric, evidence_strength="strong_logged_search_result"))
        if len(rows) >= limit:
            break
    return rows


def _bilibili_published_at(value: str, captured_at: str) -> str:
    current = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    text = str(value or "").strip().lstrip("·").strip()
    relative = re.fullmatch(r"(\d+)\s*(分钟|小时|天)前", text)
    if relative:
        amount = int(relative.group(1))
        delta = {
            "分钟": timedelta(minutes=amount),
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
        }[relative.group(2)]
        return (current - delta).astimezone(timezone.utc).isoformat()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).isoformat()
        if re.fullmatch(r"\d{2}-\d{2}", text):
            parsed = datetime.fromisoformat(f"{current.year}-{text}").replace(tzinfo=timezone.utc)
            if parsed > current:
                parsed = parsed.replace(year=current.year - 1)
            return parsed.isoformat()
    except ValueError:
        return ""
    return ""


def parse_bilibili_search_cards(
    cards: list[dict[str, str]],
    *,
    query: str,
    captured_at: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build strict Bilibili evidence from visible search-card fields."""
    rows = []
    seen = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        id_match = re.search(r"/video/(BV[0-9A-Za-z]+)", href, re.I)
        if not id_match:
            continue
        bvid = id_match.group(1)
        if bvid in seen:
            continue
        title = strip_markup(str(card.get("text") or ""))
        lines = [strip_markup(line) for line in str(card.get("context") or "").splitlines() if strip_markup(line)]
        date_index = next(
            (index for index, line in enumerate(lines) if _bilibili_published_at(line, captured_at)),
            -1,
        )
        author = lines[date_index - 1] if date_index > 0 else ""
        if not author or date_index < 0:
            continue
        published_at = _bilibili_published_at(lines[date_index], captured_at)
        duration_index = next(
            (index for index in range(date_index - 1, -1, -1) if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", lines[index])),
            -1,
        )
        if duration_index >= 0:
            visible_title = "".join(lines[duration_index + 1:date_index - 1]).strip()
            if visible_title:
                title = visible_title
            metric_values = [
                line for line in lines[:duration_index]
                if re.fullmatch(r"\d+(?:[,.]\d+)*(?:\.\d+)?(?:K|M|万)?", line, re.I)
            ][-2:]
        else:
            metric_values = [
                line for line in lines[date_index + 1:]
                if re.fullmatch(r"\d+(?:[,.]\d+)*(?:\.\d+)?(?:K|M|万)?", line, re.I)
            ]
        if not _looks_like_content_line(title, query):
            continue
        if not metric_values or _metric_number(metric_values[0]) <= 0:
            continue
        metrics = {"views": int(_metric_number(metric_values[0]))}
        if len(metric_values) > 1:
            metrics["danmaku"] = int(_metric_number(metric_values[1]))
        canonical_url = f"https://www.bilibili.com/video/{bvid}"
        snapshot = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        row = _work(
            "bilibili",
            "bilibili_logged_search",
            query,
            title,
            url=canonical_url,
            engagement=metrics["views"],
            evidence_strength="strong_logged_search_result",
        )
        row.update({
            "account_lane": query,
            "content_id": bvid,
            "canonical_url": canonical_url,
            "author_id_hash": hashlib.sha256(f"bilibili-visible:{author}".encode("utf-8")).hexdigest(),
            "published_at": published_at,
            "captured_at": captured_at,
            "fetched_at": captured_at,
            "metrics": metrics,
            "metric_observed_at": captured_at,
            "raw_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
            "views": metrics["views"],
            "detail_collector": "bilibili_visible_search_card",
            "detail_enrichment_status": "search_card_verified",
        })
        seen.add(bvid)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _juejin_published_at(value: str, captured_at: str) -> str:
    current = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    text = str(value or "").strip().lstrip("·").strip()
    relative = re.fullmatch(r"(\d+)\s*(分钟|小时|天)前", text)
    if relative:
        amount = int(relative.group(1))
        delta = {
            "分钟": timedelta(minutes=amount),
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
        }[relative.group(2)]
        published = current - delta
        if current - published <= timedelta(days=30):
            return published.astimezone(timezone.utc).isoformat()
        return ""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            published = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        elif re.fullmatch(r"\d{2}-\d{2}", text):
            published = datetime.fromisoformat(f"{current.year}-{text}").replace(tzinfo=timezone.utc)
            if published > current:
                published = published.replace(year=current.year - 1)
        else:
            return ""
    except ValueError:
        return ""
    return published.isoformat() if timedelta(0) <= current - published <= timedelta(days=30) else ""


def parse_juejin_search_cards(
    cards: list[dict[str, str]],
    *,
    query: str,
    captured_at: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build strict Juejin evidence from recent visible article cards."""
    rows = []
    seen = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        id_match = re.search(r"/post/(\d+)", href)
        if not id_match:
            continue
        content_id = id_match.group(1)
        if content_id in seen:
            continue
        title = strip_markup(str(card.get("text") or ""))
        if not _looks_like_content_line(title, query):
            continue
        lines = [strip_markup(line) for line in str(card.get("context") or "").splitlines() if strip_markup(line)]
        date_index = next(
            (index for index, line in enumerate(lines) if _juejin_published_at(line, captured_at)),
            -1,
        )
        if date_index != 1 or not lines[0]:
            continue
        published_at = _juejin_published_at(lines[date_index], captured_at)
        metric_values = [
            line for line in lines[date_index + 1:]
            if re.fullmatch(r"\d+(?:[,.]\d+)*(?:\.\d+)?(?:K|M|万)?", line, re.I)
        ]
        if not metric_values or _metric_number(metric_values[0]) <= 0:
            continue
        metric = int(_metric_number(metric_values[0]))
        canonical_url = f"https://juejin.cn/post/{content_id}"
        snapshot = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        row = _work(
            "juejin",
            "juejin_visible_search_card",
            query,
            title,
            url=canonical_url,
            engagement=metric,
            evidence_strength="strong_logged_search_result",
        )
        row.update({
            "account_lane": query,
            "content_id": content_id,
            "canonical_url": canonical_url,
            "author_id_hash": hashlib.sha256(f"juejin-visible:{lines[0]}".encode("utf-8")).hexdigest(),
            "published_at": published_at,
            "captured_at": captured_at,
            "fetched_at": captured_at,
            "metrics": {"engagement": metric},
            "metric_observed_at": captured_at,
            "raw_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
            "detail_collector": "juejin_visible_search_card",
            "detail_enrichment_status": "search_card_verified",
        })
        seen.add(content_id)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _youtube_published_at(value: str, captured_at: str) -> str:
    current = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    text = str(value or "").casefold().strip()
    english = re.search(r"(\d+)\s+(minute|hour|day|week)s?\s+ago", text)
    chinese = re.search(r"(\d+)\s*(分钟|小时|天|周)前", text)
    if english:
        amount = int(english.group(1))
        unit = english.group(2)
        delta = {
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
        }[unit]
    elif chinese:
        amount = int(chinese.group(1))
        delta = {
            "分钟": timedelta(minutes=amount),
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
            "周": timedelta(weeks=amount),
        }[chinese.group(2)]
    else:
        return ""
    return (current - delta).astimezone(timezone.utc).isoformat() if delta <= timedelta(days=30) else ""


def parse_youtube_search_cards(
    cards: list[dict[str, str]],
    *,
    query: str,
    captured_at: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Build strict YouTube evidence from this-month visible video cards."""
    rows = []
    seen = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        parsed = urllib.parse.urlsplit(href)
        query_values = urllib.parse.parse_qs(parsed.query)
        video_id = str((query_values.get("v") or [""])[0])
        if not video_id:
            shorts = re.search(r"/shorts/([0-9A-Za-z_-]+)", parsed.path)
            video_id = shorts.group(1) if shorts else ""
        if not re.fullmatch(r"[0-9A-Za-z_-]{6,20}", video_id) or video_id in seen:
            continue
        title = strip_markup(str(card.get("text") or ""))
        if not _looks_like_content_line(title, query):
            continue
        lines = [strip_markup(line) for line in str(card.get("context") or "").splitlines() if strip_markup(line)]
        age_index = next((index for index, line in enumerate(lines) if _youtube_published_at(line, captured_at)), -1)
        if age_index < 0:
            continue
        published_at = _youtube_published_at(lines[age_index], captured_at)
        view_line = next(
            (line for line in lines[:age_index] if re.search(r"\d[\d,.]*(?:\.\d+)?(?:K|M|B|万)?\s*(?:views|次观看)", line, re.I)),
            "",
        )
        view_match = re.search(r"(\d[\d,.]*(?:\.\d+)?(?:K|M|B|万)?)\s*(?:views|次观看)", view_line, re.I)
        views = _metric_number(view_match.group(1)) if view_match else 0
        try:
            title_index = lines.index(title)
        except ValueError:
            title_index = 0
        author_before_age = next(
            (
                line for line in lines[title_index + 1:age_index]
                if line not in {"•", title, view_line} and not re.fullmatch(r"\d+(?::\d+)+", line)
            ),
            "",
        )
        author_after_age = next(
            (
                line for line in lines[age_index + 1:]
                if line not in {"•", title, view_line} and not re.fullmatch(r"\d+(?::\d+)+", line)
            ),
            "",
        )
        author = author_before_age or author_after_age
        if not author or views <= 0:
            continue
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        snapshot = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        row = _work(
            "youtube",
            "youtube_visible_search_card",
            query,
            title,
            url=canonical_url,
            engagement=int(views),
            evidence_strength="strong_logged_search_result",
        )
        row.update({
            "account_lane": query,
            "content_id": video_id,
            "canonical_url": canonical_url,
            "author_id_hash": hashlib.sha256(f"youtube-visible:{author}".encode("utf-8")).hexdigest(),
            "published_at": published_at,
            "captured_at": captured_at,
            "fetched_at": captured_at,
            "metrics": {"views": int(views)},
            "metric_observed_at": captured_at,
            "raw_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
            "views": int(views),
            "detail_collector": "youtube_visible_search_card",
            "detail_enrichment_status": "search_card_verified",
        })
        seen.add(video_id)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _has_bilibili_card_contract(row: dict[str, Any]) -> bool:
    return bool(
        row.get("content_id")
        and row.get("author_id_hash")
        and row.get("published_at")
        and isinstance(row.get("metrics"), dict)
        and row.get("raw_snapshot_sha256")
    )


def enrich_bilibili_work(
    row: dict[str, Any],
    *,
    fetch_json: Any | None = None,
) -> dict[str, Any]:
    """Bind a Bilibili search row to public detail identity and metrics."""
    source = dict(row)
    match = re.search(r"/video/(BV[0-9A-Za-z]+)", str(source.get("url") or ""), re.I)
    if not match:
        return {**source, "detail_enrichment_status": "invalid_content_url"}
    bvid = match.group(1)
    endpoint = "https://api.bilibili.com/x/web-interface/view?bvid=" + urllib.parse.quote(bvid)

    def default_fetch(url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    try:
        payload = (fetch_json or default_fetch)(endpoint)
    except Exception as exc:
        if _has_bilibili_card_contract(source):
            return {**source, "detail_enrichment_status": "search_card_verified_detail_unavailable", "detail_enrichment_error": type(exc).__name__}
        return {**source, "detail_enrichment_status": "failed", "detail_enrichment_error": type(exc).__name__}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("code") != 0:
        if _has_bilibili_card_contract(source):
            return {**source, "detail_enrichment_status": "search_card_verified_detail_unavailable"}
        return {**source, "detail_enrichment_status": "invalid_response"}
    owner_id = str((data.get("owner") or {}).get("mid") or "").strip()
    published = data.get("pubdate")
    stat = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    if not owner_id or not published or not stat:
        return {**source, "detail_enrichment_status": "contract_incomplete"}
    observed_at = str(source.get("captured_at") or datetime.now(timezone.utc).isoformat())
    metrics = {
        "views": int(stat.get("view") or 0),
        "likes": int(stat.get("like") or 0),
        "comments": int(stat.get("reply") or 0),
        "shares": int(stat.get("share") or 0),
        "favorites": int(stat.get("favorite") or 0),
        "danmaku": int(stat.get("danmaku") or 0),
    }
    snapshot = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        **source,
        "account_lane": str(source.get("account_lane") or source.get("query") or ""),
        "content_id": bvid,
        "canonical_url": f"https://www.bilibili.com/video/{bvid}",
        "author_id_hash": hashlib.sha256(f"bilibili:{owner_id}".encode("utf-8")).hexdigest(),
        "published_at": datetime.fromtimestamp(int(published), tz=timezone.utc).isoformat(),
        "fetched_at": observed_at,
        "metrics": metrics,
        "metric_observed_at": observed_at,
        "raw_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "views": metrics["views"],
        "likes": metrics["likes"],
        "engagement": max(metrics.values()),
        "detail_collector": "bilibili_public_view_api",
        "detail_enrichment_status": "ok",
    }


def parse_twitter_search_cards(cards: list[dict[str, str]], *, query: str, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        match = re.match(r"(https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/\d+)", href, re.I)
        if not match:
            continue
        canonical_url = match.group(1)
        if canonical_url in seen_urls:
            continue
        lines = [strip_markup(line) for line in str(card.get("context") or "").splitlines() if strip_markup(line)]
        title = next((line for line in lines if _looks_like_content_line(line, query)), "")
        metrics = [line for line in lines if re.fullmatch(r"\d+(?:[,.]\d+)*(?:\.\d+)?(?:K|M|万)?", line, re.I)]
        metric = max(metrics, key=_metric_number) if metrics else ""
        if not title or _metric_number(metric) <= 0:
            continue
        seen_urls.add(canonical_url)
        rows.append(_work("twitter", "twitter_logged_search", query, title, url=canonical_url, engagement=metric, evidence_strength="strong_logged_search_result"))
        if len(rows) >= limit:
            break
    return rows


def parse_tiktok_search_cards(cards: list[dict[str, str]], *, query: str, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        match = re.match(r"(https?://(?:www\.)?tiktok\.com/@[^/]+/video/\d+)", href, re.I)
        if not match:
            continue
        canonical_url = match.group(1)
        if canonical_url in seen_urls:
            continue
        lines = [strip_markup(line) for line in str(card.get("context") or "").splitlines() if strip_markup(line)]
        metric = next((line for line in lines[:3] if re.fullmatch(r"\d+(?:[,.]\d+)*(?:\.\d+)?(?:K|M|万)?", line, re.I)), "")
        title = next((line for line in lines if line != metric and _looks_like_content_line(line, query)), "")
        if not title or _metric_number(metric) <= 0:
            continue
        seen_urls.add(canonical_url)
        rows.append(_work("tiktok", "tiktok_logged_search", query, title, url=canonical_url, engagement=metric, evidence_strength="strong_logged_search_result"))
        if len(rows) >= limit:
            break
    return rows


def parse_zhihu_search_cards(cards: list[dict[str, str]], *, query: str, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        if not _is_content_url("zhihu", href):
            continue
        canonical_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(href)[:3], "", ""))
        if canonical_url in seen_urls:
            continue
        title = strip_markup(str(card.get("text") or ""))
        context = strip_markup(str(card.get("context") or ""))
        metric_match = re.search(r"赞同\s*(\d+(?:\.\d+)?(?:K|M|万)?)", context, re.I)
        metric = metric_match.group(1) if metric_match else ""
        if not _looks_like_content_line(title, query) or _metric_number(metric) <= 0:
            continue
        seen_urls.add(canonical_url)
        rows.append(_work("zhihu", "zhihu_logged_search", query, title, url=canonical_url, engagement=metric, evidence_strength="strong_logged_search_result"))
        if len(rows) >= limit:
            break
    return rows


def _is_shipinhao_content_url(href: str) -> bool:
    parsed = urllib.parse.urlparse(str(href or "").strip())
    host = (parsed.hostname or "").casefold()
    if host != "channels.weixin.qq.com":
        return False
    path = parsed.path.casefold().rstrip("/")
    query = {key.casefold(): value for key, value in urllib.parse.parse_qs(parsed.query).items()}
    if path.startswith("/web/pages/feed") or path.startswith("/feed/"):
        return True
    if path.startswith("/post/") and not path.endswith(("/create", "/list")):
        return True
    content_id_keys = {"object_id", "objectid", "feed_id", "feedid"}
    return "detail" in path and any(query.get(key) for key in content_id_keys)


def _visible_shipinhao_engagement(text: str) -> dict[str, str]:
    labels = {
        "播放": "plays",
        "观看": "plays",
        "点赞": "likes",
        "赞": "likes",
        "评论": "comments",
        "收藏": "favorites",
        "转发": "shares",
    }
    metrics: dict[str, str] = {}
    for label, key in labels.items():
        match = re.search(rf"{label}\s*[:：]?\s*(\d+(?:\.\d+)?(?:K|M|万)?)", str(text or ""), re.I)
        if match and _metric_number(match.group(1)) > 0:
            metrics.setdefault(key, match.group(1))
    return metrics


def parse_shipinhao_hot_work_cards(
    cards: list[dict[str, Any]],
    *,
    query: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Accept only official Video Channels works with visible engagement."""
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card in cards:
        href = str(card.get("href") or "").strip()
        if not _is_shipinhao_content_url(href):
            continue
        canonical_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(href)[:3], "", ""))
        if canonical_url in seen_urls:
            continue
        title = strip_markup(str(card.get("title") or ""))
        visible_text = str(card.get("visible_text") or "")
        if not title:
            title = next(
                (
                    strip_markup(line)
                    for line in visible_text.splitlines()
                    if strip_markup(line) and not _visible_shipinhao_engagement(line)
                ),
                "",
            )
        metrics = _visible_shipinhao_engagement(visible_text)
        if not title or not metrics:
            continue
        engagement = next((metrics[key] for key in ("plays", "likes", "comments", "favorites", "shares") if key in metrics), "")
        if _metric_number(engagement) <= 0:
            continue
        seen_urls.add(canonical_url)
        rows.append(
            _work(
                "shipinhao",
                "shipinhao_official_logged_discovery",
                query,
                title,
                url=href,
                engagement=engagement,
                visible_engagement=metrics,
                evidence_strength="strong_logged_search_result",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def finalize_shipinhao_hot_work_evidence(
    text: str,
    cards: list[dict[str, Any]],
    *,
    query: str,
    page_url: str,
    dom_snapshot_path: str,
    screenshot_path: str,
    captured_at: str,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status: dict[str, Any] = {
        "source": "shipinhao:official_logged_discovery",
        "query": query,
        "status": "failed",
        "count": 0,
        "page_url": page_url,
        "dom_snapshot_path": dom_snapshot_path,
        "screenshot_path": screenshot_path,
        "captured_at": captured_at,
    }
    lowered = str(text or "").casefold()
    login_markers = ("扫码登录", "微信登录", "登录后", "login", "二维码")
    error_markers = ("服务器出错", "刷新重试", "请求过于频繁", "访问验证", "安全验证", "challenge", "captcha")
    if "/login" in urllib.parse.urlsplit(str(page_url or "")).path.casefold() or any(token in lowered for token in login_markers):
        status["status"] = "login_required_or_captcha"
        return [], status
    if any(token in lowered for token in error_markers):
        status["status"] = "platform_error_or_rate_limited"
        return [], status
    rows = parse_shipinhao_hot_work_cards(cards, query=query, limit=limit)
    if not dom_snapshot_path or not screenshot_path:
        status["status"] = "evidence_capture_failed"
        return [], status
    if not rows:
        status["status"] = "layout_changed_or_no_real_hot_works"
        return [], status
    for row in rows:
        row.update(
            {
                "captured_at": captured_at,
                "source_page_url": page_url,
                "dom_snapshot_path": dom_snapshot_path,
                "screenshot_path": screenshot_path,
            }
        )
    status.update({"status": "ok", "count": len(rows)})
    return rows, status


def parse_logged_short_video_search_text(text: str, *, platform: str, query: str, limit: int = 12, anchors: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Extract usable hot-work rows from logged Douyin/Kuaishou search text.

    Their web DOM changes often, so this parser is deliberately conservative:
    it only emits rows whose visible text contains lane/query terms and never
    treats login/error pages as successful samples.
    """
    if anchors:
        return parse_platform_search_evidence(text, anchors=anchors, platform=platform, query=query, limit=limit)
    rows: list[dict[str, Any]] = []
    seen = set()
    for raw in str(text or "").splitlines():
        title = strip_markup(raw)
        key = title.casefold()
        if key in seen or not _looks_like_content_line(title, query):
            continue
        seen.add(key)
        rows.append(
            _work(
                platform,
                f"{platform}_logged_search",
                query,
                title,
                evidence_strength="strong_logged_search_result",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def logged_search_artifact_stem(platform: str, query: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(query))[:32].strip("_") or "query"
    digest = hashlib.sha256(str(query).encode("utf-8")).hexdigest()[:10]
    return f"{platform}_{readable}_{digest}_search"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _logged_search_cache_path(cache_dir: str | Path, platform: str, query: str) -> Path:
    digest = hashlib.sha256(f"{platform.casefold().strip()}\0{query.casefold().strip()}".encode("utf-8")).hexdigest()
    return Path(cache_dir) / platform.casefold().strip() / f"{digest}.json"


def save_logged_search_cache(
    cache_dir: str | Path,
    platform: str,
    query: str,
    rows: list[dict[str, Any]],
    status: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    platform = platform.casefold().strip()
    valid_rows = [
        dict(row) for row in rows
        if str(row.get("platform") or "").casefold() == platform
        and _is_content_url(platform, str(row.get("url") or ""))
        and _metric_number(row.get("engagement")) > 0
        and str(row.get("captured_at") or "").strip()
        and row.get("evidence_strength") in STRONG_EVIDENCE
    ]
    if status.get("status") != "ok" or not valid_rows:
        return {"saved": False, "reason": "successful_contract_complete_rows_required"}
    artifacts = []
    for key in ("text_path", "screenshot_path"):
        path = Path(str(status.get(key) or ""))
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            return {"saved": False, "reason": f"{key}_missing"}
        artifacts.append({"kind": key, "path": str(path.resolve()), "sha256": _file_sha256(path)})
    recorded_at = now or datetime.now(timezone.utc)
    destination = _logged_search_cache_path(cache_dir, platform, query)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "verified_logged_search_cache_v1",
        "platform": platform,
        "query": query,
        "recorded_at": recorded_at.astimezone(timezone.utc).isoformat(),
        "route": str(status.get("route") or ""),
        "rows": valid_rows,
        "artifacts": artifacts,
    }
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"saved": True, "path": str(destination), "row_count": len(valid_rows)}


def load_logged_search_cache(
    cache_dir: str | Path,
    platform: str,
    query: str,
    *,
    max_age_hours: float = 6,
    now: datetime | None = None,
) -> dict[str, Any]:
    platform = platform.casefold().strip()
    path = _logged_search_cache_path(cache_dir, platform, query)
    if not path.is_file() or path.is_symlink():
        return {"status": "unavailable", "rows": [], "reason": "cache_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        recorded_at = datetime.fromisoformat(str(payload.get("recorded_at") or "").replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "invalid", "rows": [], "reason": "cache_unreadable"}
    current = now or datetime.now(timezone.utc)
    age_seconds = (current.astimezone(timezone.utc) - recorded_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0 or age_seconds > max_age_hours * 3600:
        return {"status": "expired", "rows": [], "reason": "cache_outside_ttl"}
    if payload.get("schema") != "verified_logged_search_cache_v1" or payload.get("platform") != platform or payload.get("query") != query:
        return {"status": "invalid", "rows": [], "reason": "cache_identity_mismatch"}
    for artifact in payload.get("artifacts") or []:
        source = Path(str(artifact.get("path") or ""))
        if not source.is_file() or source.is_symlink() or _file_sha256(source) != artifact.get("sha256"):
            return {"status": "invalid", "rows": [], "reason": "cache_artifact_mismatch"}
    rows = [dict(row) for row in payload.get("rows") or [] if isinstance(row, dict)]
    if not rows or any(
        str(row.get("platform") or "").casefold() != platform
        or not _is_content_url(platform, str(row.get("url") or ""))
        or _metric_number(row.get("engagement")) <= 0
        for row in rows
    ):
        return {"status": "invalid", "rows": [], "reason": "cache_row_contract_failed"}
    for row in rows:
        row["source"] = f"{platform}_cached_logged_search"
        row["evidence_strength"] = "strong_cached_native_search"
        row["cache_recorded_at"] = payload["recorded_at"]
    return {"status": "ready", "rows": rows, "reason": "", "path": str(path), "age_seconds": age_seconds}


def needs_dynamic_content_wait(text: str) -> bool:
    visible = strip_markup(text)
    return len(visible) < 40


def classify_logged_search_failure(text: str, *, platform: str = "") -> str:
    lowered = str(text or "").casefold()
    try:
        payload = json.loads(str(text or ""))
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict) and payload.get("result") in {2, 3}:
        return "login_required_or_captcha"
    strong_login = any(token in lowered for token in ("验证码", "captcha"))
    normalized_platform = str(platform or "").casefold()
    normal_public_search = (
        normalized_platform == "bilibili"
        and all(token in lowered for token in ("综合排序", "最多播放", "最新发布"))
    ) or (
        normalized_platform == "juejin"
        and all(token in lowered for token in ("综合", "文章", "用户"))
    ) or (
        normalized_platform == "youtube"
        and all(token in lowered for token in ("shorts", "过滤"))
        and bool(re.search(r"\d[\d,.]*(?:\.\d+)?(?:k|m|b|万)?\s*(?:views|次观看)", lowered, re.I))
    )
    if strong_login or (not normal_public_search and any(token in lowered for token in ("登录", "login"))):
        return "login_required_or_captcha"
    if any(token in lowered for token in (
        "服务器出错", "服务器出现问题", "刷新重试", "请求过于频繁", "访问验证", "安全验证",
        "challenge", "ip存在风险", "300012",
    )):
        return "platform_error_or_rate_limited"
    return "layout_changed_or_no_lane_results"


def logged_search_url(platform: str, query: str) -> str:
    normalized = str(platform or "").casefold().strip()
    encoded = urllib.parse.quote(str(query or ""))
    urls = {
        "douyin": f"https://www.douyin.com/search/{encoded}?type=video",
        "douyin_ai": f"https://www.douyin.com/search/{encoded}?type=video",
        "douyin_pet": f"https://www.douyin.com/search/{encoded}?type=video",
        "kuaishou": f"https://www.kuaishou.com/search/video?searchKey={encoded}",
        "xiaohongshu": f"https://www.xiaohongshu.com/search_result?keyword={encoded}",
        "tiktok": f"https://www.tiktok.com/search?q={encoded}",
        "youtube": f"https://www.youtube.com/results?search_query={encoded}&sp=EgIIBA%253D%253D",
        "bilibili": f"https://search.bilibili.com/all?keyword={encoded}",
        "zhihu": f"https://www.zhihu.com/search?q={encoded}",
        "juejin": f"https://juejin.cn/search?query={encoded}&type=0&sort=1",
        "twitter": f"https://x.com/search?q={encoded}&src=typed_query",
        "shipinhao": "https://channels.weixin.qq.com/platform",
    }
    if normalized not in urls:
        raise ValueError(f"unsupported logged short-video platform: {normalized}")
    return urls[normalized]


def should_retry_logged_page(text: str) -> bool:
    lowered = str(text or "").casefold()
    return any(token in lowered for token in ("服务器出错", "服务器出现问题", "刷新重试", "请重试"))


def collect_logged_short_video_search(
    platform: str,
    query: str,
    *,
    state_file: str | Path | None,
    output_dir: str | Path,
    limit: int = 12,
    timeout_ms: int = 30000,
    proxy_url: str = "",
    route_name: str = "direct",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect a logged short-video search page with Playwright.

    This is used for platforms where public pages are unstable.  It is optional
    and only imports Playwright at call time.
    """
    from playwright.sync_api import sync_playwright

    platform = str(platform or "").casefold().strip()
    target_url = logged_search_url(platform, query)
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {"source": f"{platform}:logged_search", "query": query, "status": "failed", "count": 0, "route": route_name}
    artifact_stem = logged_search_artifact_stem(platform, query)
    text_path = base / f"{artifact_stem}.txt"
    screenshot_path = base / f"{artifact_stem}.png"
    dom_snapshot_path = base / f"{platform}_{re.sub(r'[^a-zA-Z0-9_-]+', '_', query)[:40]}_search.html"
    for artifact in (screenshot_path, dom_snapshot_path):
        artifact.unlink(missing_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sync_playwright() as pw:
        executable_path = (
            os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
            or os.environ.get("CHROME_BIN")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
        )
        launch_options: dict[str, Any] = {"headless": True}
        if proxy_url:
            normalized_proxy = "socks5://" + proxy_url[len("socks5h://"):] if proxy_url.startswith("socks5h://") else proxy_url
            launch_options["proxy"] = {"server": normalized_proxy}
        if executable_path:
            launch_options["executable_path"] = executable_path
        browser = pw.chromium.launch(**launch_options)
        context_options: dict[str, Any] = {"viewport": {"width": 1365, "height": 900}, "locale": "zh-CN"}
        if state_file and Path(state_file).is_file():
            context_options["storage_state"] = str(state_file)
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        if platform == "shipinhao":
            for label in ("内容发现", "创作灵感", "热门内容", "热点"):
                candidate = page.get_by_text(label, exact=False).first
                try:
                    if candidate.is_visible(timeout=1000):
                        candidate.click(timeout=5000)
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue
            for placeholder in ("搜索作品", "搜索内容", "搜索视频", "搜索"):
                search = page.get_by_placeholder(placeholder, exact=False).first
                try:
                    if search.is_visible(timeout=800):
                        search.fill(str(query or ""), timeout=3000)
                        search.press("Enter")
                        page.wait_for_timeout(2500)
                        break
                except Exception:
                    continue
        body = page.locator("body")
        text = body.inner_text(timeout=8000)
        dynamic_wait_ms = 0
        if needs_dynamic_content_wait(text):
            dynamic_wait_ms = min(15000, max(3000, timeout_ms // 2))
            page.wait_for_timeout(dynamic_wait_ms)
            text = body.inner_text(timeout=8000)
        page_retry_count = 0
        if should_retry_logged_page(text):
            page_retry_count = 1
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            text = body.inner_text(timeout=8000)
            if needs_dynamic_content_wait(text):
                retry_wait_ms = min(15000, max(3000, timeout_ms // 2))
                page.wait_for_timeout(retry_wait_ms)
                dynamic_wait_ms += retry_wait_ms
                text = body.inner_text(timeout=8000)
        anchors = page.locator("a[href], [data-url]").evaluate_all(
            """els => els.map(a => {
                const box = a.closest('article, li, [class*="card"], [class*="item"], [class*="video"], [class*="feed"]') || a;
                const heading = box.querySelector('h1, h2, h3, h4, [class*="title"]');
                return {
                    text: ((heading && heading.innerText) || a.innerText || a.getAttribute('aria-label') || a.title || '').trim(),
                    href: a.href || a.getAttribute('data-url') || '',
                    context: (box.innerText || '').trim()
                };
            })"""
        )
        final_url = page.url
        text_path.write_text(text, encoding="utf-8")
        dom_snapshot_path.write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            pass
        context.close()
        browser.close()
    if platform == "shipinhao":
        cards = [
            {"title": anchor.get("text", ""), "href": anchor.get("href", ""), "visible_text": anchor.get("context", anchor.get("text", ""))}
            for anchor in anchors
        ]
        return finalize_shipinhao_hot_work_evidence(
            text,
            cards,
            query=query,
            page_url=final_url,
            dom_snapshot_path=str(dom_snapshot_path) if dom_snapshot_path.is_file() else "",
            screenshot_path=str(screenshot_path) if screenshot_path.is_file() else "",
            captured_at=captured_at,
            limit=limit,
        )
    if platform == "bilibili":
        rows = parse_bilibili_search_cards(anchors, query=query, captured_at=captured_at, limit=limit)
    elif platform == "juejin":
        rows = parse_juejin_search_cards(anchors, query=query, captured_at=captured_at, limit=limit)
    elif platform == "youtube":
        rows = parse_youtube_search_cards(anchors, query=query, captured_at=captured_at, limit=limit)
    elif platform == "twitter":
        rows = parse_twitter_search_cards(anchors, query=query, limit=limit)
    elif platform == "tiktok":
        rows = parse_tiktok_search_cards(anchors, query=query, limit=limit)
    elif platform == "zhihu":
        rows = parse_zhihu_search_cards(anchors, query=query, limit=limit)
    elif platform == "xiaohongshu":
        rows = parse_xiaohongshu_search_text(text, query=query, limit=limit, anchors=anchors)
    else:
        rows = parse_logged_short_video_search_text(text, platform=platform, query=query, limit=limit, anchors=anchors)
    if platform == "bilibili" and rows:
        rows = [enrich_bilibili_work(row) for row in rows]
        rows = [row for row in rows if str(row.get("detail_enrichment_status") or "").startswith(("ok", "search_card_verified"))]
    if rows:
        status.update({"status": "ok", "count": len(rows)})
    else:
        status.update({"status": classify_logged_search_failure(text, platform=platform), "count": 0})
    status.update({"text_path": str(text_path), "screenshot_path": str(screenshot_path), "dynamic_wait_ms": dynamic_wait_ms, "page_retry_count": page_retry_count})
    return rows, status


def should_use_regional_proxy(status: dict[str, Any]) -> bool:
    return str(status.get("status") or "") == "platform_error_or_rate_limited"


def _decode_js_string(value: str) -> str:
    try:
        return value.encode("utf-8").decode("unicode_escape", errors="ignore")
    except Exception:
        return value


def parse_douyin_shipin_html(raw_html: str, *, query: str, platform: str = "douyin_ai", limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r'"awemeId":"(?P<id>\d+)".{0,4000}?"text":"(?P<text>.*?)".{0,4000}?"nickname":"(?P<nick>.*?)".{0,4000}?"diggCount":(?P<likes>\d+).{0,4000}?"videoUrl":"(?P<url>.*?)".{0,4000}?"duration":(?P<duration>\d+)',
        re.S,
    )
    for match in pattern.finditer(raw_html):
        title = _decode_js_string(match.group("text"))
        rows.append(
            _work(
                platform,
                "douyin_shipin_public",
                query,
                title,
                id=match.group("id"),
                author=_decode_js_string(match.group("nick")),
                likes=int(match.group("likes")),
                url=match.group("url").replace("\\/", "/"),
                duration_ms=int(match.group("duration")),
                evidence_strength="strong_public_shipin_related",
            )
        )
        if len(rows) >= limit:
            break
    transcript_match = re.search(r"data-e2e=['\"]ai-text['\"]>(.*?)</p>", raw_html, flags=re.S)
    if transcript_match:
        rows.append(
            _work(
                platform,
                "douyin_shipin_ai_transcript",
                query,
                strip_markup(transcript_match.group(1))[:80] or "页面主视频AI文稿",
                excerpt=strip_markup(transcript_match.group(1))[:800],
                url=f"https://m.douyin.com/shipin/{urllib.parse.quote(query)}",
                evidence_strength="strong_public_transcript",
            )
        )
    return rows


def fetch_url(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8", "ignore")


def collect_wechat(query: str, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://weixin.sogou.com/weixin?type=2&query=" + urllib.parse.quote(query)
    return parse_sogou_wechat_html(fetch_url(url), query=query, limit=limit)


def collect_douyin_shipin(query: str, platform: str, limit: int = 12) -> list[dict[str, Any]]:
    url = "https://m.douyin.com/shipin/" + urllib.parse.quote(query)
    return parse_douyin_shipin_html(fetch_url(url, timeout=30), query=query, platform=platform, limit=limit)


def _metric_number(value: Any) -> float:
    text = str(value or "").replace(",", "").strip().upper()
    if not text:
        return 0.0
    try:
        if text.endswith("K"):
            return float(text[:-1]) * 1000
        if text.endswith("M"):
            return float(text[:-1]) * 1_000_000
        if "万" in text:
            return float(text.replace("万", "")) * 10_000
        return float(text)
    except ValueError:
        return 0.0


def build_hot_work_parameter_pack(samples: list[dict[str, Any]], *, platforms: list[str] | None = None, min_strong_samples: int = 3) -> dict[str, Any]:
    from .platform_intelligence_registry import publishing_platforms

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.get("platform") or "unknown")].append(sample)
    default_platforms = publishing_platforms()
    selected_platforms = list(platforms) if platforms is not None else default_platforms
    output: dict[str, Any] = {"generated_at": datetime.now().isoformat(timespec="seconds"), "platforms": {}}
    for platform in selected_platforms:
        rows = sorted(
            grouped.get(platform, []),
            key=lambda row: _metric_number(row.get("views") or row.get("likes") or row.get("favorites") or row.get("engagement")),
            reverse=True,
        )
        strong = [
            row for row in rows
            if row.get("evidence_strength") in STRONG_EVIDENCE
            and str(row.get("url") or "").startswith(("http://", "https://"))
            and bool(row.get("captured_at"))
            and bool(row.get("collector"))
            and _metric_number(row.get("views") or row.get("likes") or row.get("favorites") or row.get("engagement")) > 0
        ]
        patterns = Counter()
        for row in strong:
            for key in ("hook_types", "structure_types", "copy_style", "display_style"):
                for value in (row.get("analysis") or {}).get(key, []):
                    patterns[value] += 1
        output["platforms"][platform] = {
            "ready": len(strong) >= min_strong_samples,
            "strong_sample_count": len(strong),
            "sample_count": len(rows),
            "top_samples": strong[:10],
            "cross_platform_references": _cross_platform_references(platform, samples),
            "recommended_patterns": [name for name, _count in patterns.most_common(10)],
            "generation_requirements": _generation_requirements(platform, patterns),
        }
    return output


def _cross_platform_references(platform: str, samples: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    from .intelligence_scoring import evaluate_intelligence_pool
    from .platform_intelligence_registry import platform_queries

    rows = []
    for row in samples:
        if not isinstance(row, dict) or str(row.get("platform") or "").casefold() == str(platform).casefold():
            continue
        if str(row.get("identity_role") or "") != "cross_platform_reference":
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue
        rows.append({
            "title": title[:160],
            "platform": str(row.get("platform") or ""),
            "source": str(row.get("source") or ""),
            "url": url,
            "metric": row.get("heat") or row.get("points") or row.get("engagement") or 0,
            "captured_at": str(row.get("captured_at") or ""),
            "identity_role": "cross_platform_reference",
            "analysis": row.get("analysis") or analyze_work(title),
        })
    keywords = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", " ".join(platform_queries(platform)).casefold())
    ranked = evaluate_intelligence_pool(rows, target_platform=platform, lane_keywords=keywords)
    return [
        row for row in ranked
        if float((row.get("intelligence_score") or {}).get("dimensions", {}).get("lane_fit") or 0) > 0
    ][: max(0, int(limit))]


def _generation_requirements(platform: str, patterns: Counter[str]) -> list[str]:
    requirements = [
        "topic must cite same-platform same-lane hot works",
        "opening must show result, conflict, or proof before explanation",
        "claims require screenshots, recordings, links, commands, or run output",
    ]
    if platform in {"douyin_ai", "tiktok", "kuaishou"}:
        requirements.append("video scenes must contain real UI/demo footage before mascot or abstract cards")
    if platform == "xiaohongshu":
        requirements.append("first card must combine concrete tool, result, and save-worthy list structure")
    if platform in {"wechat", "zhihu", "juejin"}:
        requirements.append("long-form content needs H2/H3 sections, examples, evidence assets, and action checklist")
    if "对比评测" in patterns:
        requirements.append("include side-by-side comparison with explicit decision rule")
    return requirements


def save_hot_work_strategy_report(pack: dict[str, Any], output: str | Path) -> Path:
    lines = ["# 热门作品参数包与 Hermes 生成策略", "", f"生成时间: {pack.get('generated_at')}", ""]
    for platform, data in pack.get("platforms", {}).items():
        lines.extend(
            [
                f"## {platform}",
                "",
                f"- ready: {data.get('ready')}",
                f"- strong_sample_count: {data.get('strong_sample_count')}",
                f"- recommended_patterns: {', '.join(data.get('recommended_patterns') or [])}",
                "- generation_requirements:",
            ]
        )
        lines.extend(f"  - {row}" for row in data.get("generation_requirements", []))
        lines.append("- top_samples:")
        for sample in data.get("top_samples", [])[:5]:
            metric = sample.get("views") or sample.get("likes") or sample.get("favorites") or sample.get("engagement") or ""
            lines.append(f"  - {sample.get('title')} | {sample.get('author', '')} | {metric} | {sample.get('evidence_strength')}")
        lines.append("")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_samples(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    direct = data.get("items") or data.get("samples")
    if isinstance(direct, list):
        return list(direct)
    rows: list[dict[str, Any]] = []
    for platform, value in data.items():
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    row.setdefault("platform", str(platform))
                    rows.append(row)
    return rows


def save_collection(
    items: list[dict[str, Any]], statuses: list[dict[str, Any]], output_dir: str | Path,
    *, publish_latest: bool = True,
) -> dict[str, str]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "items": items, "collection_status": statuses}
    raw_path = base / "hot_works_raw.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pack = build_hot_work_parameter_pack(items)
    pack_path = base / "hot_work_parameter_pack.json"
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = save_hot_work_strategy_report(pack, base / "hot_work_strategy_report.md")
    mutable_root = Path(os.environ.get("CONTENT_PLATFORM_DATA_DIR") or os.environ.get("AI_SELF_MEDIA_DATA_DIR") or "data")
    latest = mutable_root / "intel" / "hot_work_parameter_pack_latest.json"
    if publish_latest:
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"raw": str(raw_path), "pack": str(pack_path), "report": str(report_path), "latest": str(latest) if publish_latest else ""}
