import re
from collections import Counter
from urllib.parse import urlparse


SHORT_VIDEO_PLATFORMS = {"douyin", "tiktok", "youtube", "bilibili", "kuaishou"}
NOTE_PLATFORMS = {"xiaohongshu", "rednote", "instagram", "threads"}
ARTICLE_PLATFORMS = {"wechat", "weixin", "devto", "linkedin", "telegraph", "mataroa", "tabnews"}


def infer_platform(value):
    text = str(value or "").casefold()
    for platform in SHORT_VIDEO_PLATFORMS | NOTE_PLATFORMS | ARTICLE_PLATFORMS:
        if platform in text:
            return platform
    parsed = urlparse(text)
    host = parsed.netloc.casefold()
    if "xiaohongshu" in host or "xhslink" in host:
        return "xiaohongshu"
    if "douyin" in host:
        return "douyin"
    if "bilibili" in host:
        return "bilibili"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if "weixin" in host or "wechat" in host:
        return "wechat"
    return ""


def _host(value):
    parsed = urlparse(str(value or "").strip())
    return parsed.netloc.casefold().lstrip("www.")


def _fingerprint(parts):
    text = "|".join(str(part or "").strip().casefold() for part in parts if str(part or "").strip())
    return re.sub(r"[^a-z0-9|:_/-]+", "-", text)[:160]


def _derive_account_handle(row):
    handle = str(row.get("account_handle") or row.get("author") or row.get("source") or "").strip()
    if handle:
        return handle
    host = _host(row.get("url", "") or row.get("source", ""))
    path = urlparse(str(row.get("url", "")).strip()).path.strip("/")
    if host and path:
        return f"{host}:{path.split('/')[0]}"
    return host


def detect_topic_signals(text):
    tokens = re.findall(r"[A-Za-z0-9_+#-]{3,}|[\u4e00-\u9fff]{2,8}", str(text or ""))
    counts = Counter(token.casefold() for token in tokens)
    return [token for token, _ in counts.most_common(8)]


def normalize_source_items(topic, brief, reference_posts):
    brief = brief or {}
    items = []
    for row in reference_posts or []:
        title = str(row.get("title", "")).strip()
        body = str(row.get("body", "")).strip()
        url = str(row.get("url", "")).strip()
        source = str(row.get("source", "")).strip()
        account_handle = _derive_account_handle(row)
        platform = str(row.get("platform") or infer_platform(source) or infer_platform(url)).strip()
        source_host = _host(url or source)
        items.append(
            {
                "source_type": "reference_post",
                "topic": topic,
                "platform": platform,
                "account_handle": account_handle,
                "display_name": str(row.get("display_name") or account_handle),
                "title": title,
                "body": body,
                "url": url,
                "source": source,
                "source_host": source_host,
                "fingerprint": _fingerprint([topic, platform, account_handle, title, url]),
                "content_forms": detect_content_forms(title, body),
                "topic_signals": detect_topic_signals(f"{title}\n{body}"),
            }
        )
    for raw_url in brief.get("sources", []):
        source_url = str(raw_url).strip()
        platform = infer_platform(source_url)
        items.append(
            {
                "source_type": "source_url",
                "topic": topic,
                "platform": platform,
                "account_handle": "",
                "display_name": "",
                "title": "",
                "body": "",
                "url": source_url,
                "source": source_url,
                "source_host": _host(source_url),
                "fingerprint": _fingerprint([topic, platform, source_url]),
                "content_forms": [],
                "topic_signals": detect_topic_signals(source_url),
            }
        )
    return items


def summarize_source_items(items):
    items = [item for item in items or [] if any(item.get(field) for field in ("title", "body", "url"))]
    platform_counts = Counter(item.get("platform", "") for item in items if item.get("platform"))
    account_counts = Counter(item.get("account_handle", "") for item in items if item.get("account_handle"))
    host_counts = Counter(item.get("source_host", "") for item in items if item.get("source_host"))
    return {
        "sample_count": len(items),
        "account_count": len(account_counts),
        "url_count": sum(1 for item in items if item.get("url")),
        "platform_distribution": dict(platform_counts),
        "top_accounts": [account for account, _ in account_counts.most_common(5)],
        "source_hosts": [host for host, _ in host_counts.most_common(5)],
    }


def detect_content_forms(title, body):
    text = f"{title}\n{body}".casefold()
    forms = set()
    if re.search(r"(^|\n)\s*\d+[.)]", body):
        forms.add("listicle")
    if "how " in text or "guide" in text or "教程" in text:
        forms.add("tutorial")
    if "case study" in text or "案例" in text:
        forms.add("case_study")
    if "script" in text or "hook" in text or "脚本" in text:
        forms.add("short_script")
    if "?" in title or "？" in title:
        forms.add("question_hook")
    return sorted(forms)
