import re
from collections import Counter

from .sources import detect_content_forms, summarize_source_items


def _opening_sentence(body):
    parts = re.split(r"[.!?\u3002\uff01\uff1f\n]", str(body).strip(), maxsplit=1)
    return parts[0].strip()[:80] if parts and parts[0].strip() else ""


def analyze_niche(topic, posts):
    posts = [row for row in (posts or []) if row.get("title") or row.get("body") or row.get("url")]
    summary = summarize_source_items(posts)
    formats = set()
    cta_hits = Counter()
    openings = []
    account_roles = {}
    account_samples = Counter()
    narrative_devices = Counter()
    for row in posts:
        forms = detect_content_forms(row.get("title", ""), row.get("body", ""))
        formats.update(forms)
        opening = _opening_sentence(row.get("body", ""))
        if opening:
            openings.append(opening)
        text = f"{row.get('title', '')}\n{row.get('body', '')}"
        if ":" in row.get("title", ""):
            narrative_devices["colon_titles"] += 1
        if re.search(r"(^|\n)\s*\d+[.)]", row.get("body", "")):
            narrative_devices["numbered_steps"] += 1
        for token in ("save this", "follow", "comment", "收藏", "关注", "评论"):
            if token.casefold() in text.casefold():
                cta_hits[token] += 1
        handle = row.get("account_handle", "")
        if handle:
            account_samples[handle] += 1
            role = (
                "educator"
                if "tutorial" in forms or "listicle" in forms
                else "storyteller"
                if "case_study" in forms
                else "commentator"
                if "question_hook" in forms
                else "operator"
            )
            account_roles.setdefault(handle, role)
    return {
        "topic": topic,
        "sample_count": summary["sample_count"],
        "account_count": summary["account_count"],
        "platform_distribution": summary["platform_distribution"],
        "top_accounts": summary["top_accounts"],
        "source_hosts": summary.get("source_hosts", []),
        "account_roles": account_roles,
        "account_sample_count": dict(account_samples),
        "style_signature": {
            "formats": sorted(formats),
            "opening_patterns": openings[:5],
            "cta_keywords": [token for token, _ in cta_hits.most_common(5)],
            "narrative_devices": dict(narrative_devices),
        },
    }
