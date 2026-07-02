import re
from collections import Counter

from .sources import detect_content_forms, summarize_source_items


def _opening_sentence(body):
    parts = re.split(r"[.!?。！？\n]", str(body).strip(), maxsplit=1)
    return parts[0].strip()[:80] if parts and parts[0].strip() else ""


def analyze_niche(topic, posts):
    posts = [row for row in (posts or []) if row.get("title") or row.get("body") or row.get("url")]
    summary = summarize_source_items(posts)
    formats = set()
    cta_hits = Counter()
    openings = []
    account_roles = {}
    for row in posts:
        forms = detect_content_forms(row.get("title", ""), row.get("body", ""))
        formats.update(forms)
        opening = _opening_sentence(row.get("body", ""))
        if opening:
            openings.append(opening)
        text = f"{row.get('title', '')}\n{row.get('body', '')}"
        for token in ("save this", "follow", "comment", "收藏", "关注", "评论"):
            if token.casefold() in text.casefold():
                cta_hits[token] += 1
        handle = row.get("account_handle", "")
        if handle:
            role = "educator" if "tutorial" in forms or "listicle" in forms else "storyteller" if "case_study" in forms else "operator"
            account_roles.setdefault(handle, role)
    return {
        "topic": topic,
        "sample_count": summary["sample_count"],
        "account_count": summary["account_count"],
        "platform_distribution": summary["platform_distribution"],
        "top_accounts": summary["top_accounts"],
        "account_roles": account_roles,
        "style_signature": {
            "formats": sorted(formats),
            "opening_patterns": openings[:5],
            "cta_keywords": [token for token, _ in cta_hits.most_common(5)],
        },
    }
