"""
RSS Ingest — fetch RSS/Atom feeds, normalize into source items for intelligence pipeline.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime
from xml.etree import ElementTree


def _fetch_feed(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-self-media-tools/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_rss(data):
    items = []
    root = ElementTree.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//item"):
        item = {
            "title": (entry.findtext("title") or "").strip(),
            "url": (entry.findtext("link") or "").strip(),
            "summary": (entry.findtext("description") or "").strip()[:500],
            "published": entry.findtext("pubDate", ""),
            "source": _extract_domain(entry.findtext("link", "")),
        }
        if item["title"]:
            items.append(item)
    for entry in root.findall(".//atom:entry", ns):
        link = entry.find("atom:link", ns)
        item = {
            "title": (entry.findtext("atom:title", "", ns) or "").strip(),
            "url": link.get("href", "") if link is not None else "",
            "summary": (entry.findtext("atom:summary", "", ns) or "").strip()[:500],
            "published": entry.findtext("atom:updated", "", ns),
            "source": _extract_domain(link.get("href", "") if link is not None else ""),
        }
        if item["title"]:
            items.append(item)
    return items


def _extract_domain(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def ingest_feed(url, store=None, topic=""):
    try:
        data = _fetch_feed(url)
        items = _parse_rss(data)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "items": []}
    normalized = []
    for item in items:
        normalized.append({
            "source_type": "rss_item",
            "platform": "rss",
            "account_handle": item["source"],
            "title": item["title"],
            "url": item["url"],
            "body": item["summary"],
            "source_url": item["url"],
            "source_host": item["source"],
            "topic_signals": [topic] if topic else [],
        })
    if store and normalized:
        job = store.create_job(f"rss-ingest-{topic or 'feed'}", ["file"],
                               {"rss_feed": url, "rss_items": len(normalized)})
        store.save_source_items(job["id"], normalized)
    return {"ok": True, "count": len(normalized), "items": normalized}


def ingest_multi(feeds, store=None):
    total = 0
    errors = []
    for feed in feeds:
        if isinstance(feed, str):
            result = ingest_feed(feed, store)
        else:
            result = ingest_feed(feed["url"], store, feed.get("topic", ""))
        if result["ok"]:
            total += result["count"]
        else:
            errors.append({"url": feed if isinstance(feed, str) else feed["url"], "error": result["error"]})
    return {"ok": len(errors) == 0, "total_items": total, "errors": errors}
