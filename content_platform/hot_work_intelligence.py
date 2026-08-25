from __future__ import annotations

import html
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
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
        if re.fullmatch(r"20\d{2}(?:[-/.]\d{1,2})?(?:[-/.]\d{1,2})?", line.strip()):
            continue
        match = re.search(r"(?:赞同|点赞|播放|观看|喜欢|收藏|评论)?\s*(\d+(?:\.\d+)?(?:K|M|万)?)", line, re.I)
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
    for anchor in anchors:
        title = strip_markup(str(anchor.get("text") or ""))
        href = str(anchor.get("href") or "").strip()
        key = title.casefold()
        if key in seen or key in blocked_titles or not href.startswith(("http://", "https://")):
            continue
        if not _is_content_url(platform, href):
            continue
        if not _looks_like_content_line(title, query):
            continue
        metric = _nearby_metric(lines, title)
        if _metric_number(metric) <= 0:
            continue
        seen.add(key)
        rows.append(_work(platform, f"{platform}_logged_search", query, title, url=href, engagement=metric, evidence_strength="strong_logged_search_result"))
        if len(rows) >= limit:
            break
    return rows


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


def collect_logged_short_video_search(
    platform: str,
    query: str,
    *,
    state_file: str | Path | None,
    output_dir: str | Path,
    limit: int = 12,
    timeout_ms: int = 30000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect a logged short-video search page with Playwright.

    This is used for platforms where public pages are unstable.  It is optional
    and only imports Playwright at call time.
    """
    from playwright.sync_api import sync_playwright

    platform = str(platform or "").casefold().strip()
    encoded = urllib.parse.quote(str(query or ""))
    urls = {
        "douyin": f"https://www.douyin.com/search/{encoded}?type=video",
        "douyin_ai": f"https://www.douyin.com/search/{encoded}?type=video",
        "douyin_pet": f"https://www.douyin.com/search/{encoded}?type=video",
        "kuaishou": f"https://www.kuaishou.com/search/video?searchKey={encoded}",
        "xiaohongshu": f"https://www.xiaohongshu.com/search_result?keyword={encoded}",
        "tiktok": f"https://www.tiktok.com/search?q={encoded}",
        "youtube": f"https://www.youtube.com/results?search_query={encoded}",
        "bilibili": f"https://search.bilibili.com/all?keyword={encoded}",
        "zhihu": f"https://www.zhihu.com/search?q={encoded}",
        "juejin": f"https://juejin.cn/search?query={encoded}",
        "twitter": f"https://x.com/search?q={encoded}&src=typed_query",
    }
    if platform not in urls:
        raise ValueError(f"unsupported logged short-video platform: {platform}")
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {"source": f"{platform}:logged_search", "query": query, "status": "failed", "count": 0}
    text_path = base / f"{platform}_{re.sub(r'[^a-zA-Z0-9_-]+', '_', query)[:40]}_search.txt"
    screenshot_path = base / f"{platform}_{re.sub(r'[^a-zA-Z0-9_-]+', '_', query)[:40]}_search.png"
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
        if executable_path:
            launch_options["executable_path"] = executable_path
        browser = pw.chromium.launch(**launch_options)
        context_options: dict[str, Any] = {"viewport": {"width": 1365, "height": 900}, "locale": "zh-CN"}
        if state_file and Path(state_file).is_file():
            context_options["storage_state"] = str(state_file)
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.goto(urls[platform], wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        text = page.locator("body").inner_text(timeout=8000)
        anchors = page.locator("a").evaluate_all(
            "els => els.map(a => ({text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim(), href: a.href || ''}))"
        )
        text_path.write_text(text, encoding="utf-8")
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            pass
        context.close()
        browser.close()
    if platform == "xiaohongshu":
        rows = parse_xiaohongshu_search_text(text, query=query, limit=limit, anchors=anchors)
    else:
        rows = parse_logged_short_video_search_text(text, platform=platform, query=query, limit=limit, anchors=anchors)
    lowered = text.casefold()
    if rows:
        status.update({"status": "ok", "count": len(rows)})
    elif any(token in lowered for token in ("登录", "验证码", "login", "captcha")):
        status.update({"status": "login_required_or_captcha", "count": 0})
    elif any(token in text for token in ("服务器出错", "刷新重试", "请求过于频繁")):
        status.update({"status": "platform_error_or_rate_limited", "count": 0})
    else:
        status.update({"status": "layout_changed_or_no_lane_results", "count": 0})
    status.update({"text_path": str(text_path), "screenshot_path": str(screenshot_path)})
    return rows, status


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
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.get("platform") or "unknown")].append(sample)
    default_platforms = ["wechat", "kuaishou", "bilibili", "zhihu", "juejin", "douyin_ai", "douyin_pet", "xiaohongshu", "tiktok", "youtube"]
    selected_platforms = platforms or sorted(set(grouped).union(default_platforms))
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
            "recommended_patterns": [name for name, _count in patterns.most_common(10)],
            "generation_requirements": _generation_requirements(platform, patterns),
        }
    return output


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


def save_collection(items: list[dict[str, Any]], statuses: list[dict[str, Any]], output_dir: str | Path) -> dict[str, str]:
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
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"raw": str(raw_path), "pack": str(pack_path), "report": str(report_path), "latest": str(latest)}
