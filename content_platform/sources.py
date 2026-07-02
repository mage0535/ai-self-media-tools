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


def normalize_source_items(topic, brief, reference_posts):
    brief = brief or {}
    items = []
    for row in reference_posts or []:
        account_handle = str(row.get("account_handle") or row.get("author") or row.get("source") or "").strip()
        platform = str(row.get("platform") or infer_platform(row.get("source", "")) or infer_platform(row.get("url", ""))).strip()
        items.append(
            {
                "source_type": "reference_post",
                "topic": topic,
                "platform": platform,
                "account_handle": account_handle,
                "display_name": str(row.get("display_name") or account_handle),
                "title": str(row.get("title", "")).strip(),
                "body": str(row.get("body", "")).strip(),
                "url": str(row.get("url", "")).strip(),
                "source": str(row.get("source", "")).strip(),
            }
        )
    for url in brief.get("sources", []):
        items.append(
            {
                "source_type": "source_url",
                "topic": topic,
                "platform": infer_platform(url),
                "account_handle": "",
                "display_name": "",
                "title": "",
                "body": "",
                "url": str(url).strip(),
                "source": str(url).strip(),
            }
        )
    return items


def summarize_source_items(items):
    items = [item for item in items or [] if any(item.get(field) for field in ("title", "body", "url"))]
    platform_counts = Counter(item.get("platform", "") for item in items if item.get("platform"))
    account_counts = Counter(item.get("account_handle", "") for item in items if item.get("account_handle"))
    return {
        "sample_count": len(items),
        "account_count": len(account_counts),
        "url_count": sum(1 for item in items if item.get("url")),
        "platform_distribution": dict(platform_counts),
        "top_accounts": [account for account, _ in account_counts.most_common(5)],
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
