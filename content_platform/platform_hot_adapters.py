"""Read-only adapters for auditable, platform-bound hot-data snapshots.

The module deliberately separates topic signals from content snapshots.  It never
logs in, launches browsers, invokes MediaCrawler, handles credentials, or marks
third-party results as native platform evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .hot_evidence_fusion import fuse_platform_hot_evidence
from .same_lane_intelligence import AI_LANE_TERMS
from .real_world_ai_policy import (
    build_discovery_queries,
    classify_discovery_text,
    load_real_world_ai_positioning,
)
from .real_world_ai_triage import triage_real_world_ai_candidate
from .public_work_metadata import PublicWorkMetadataAdapter


JsonFetcher = Callable[[str], dict[str, Any]]
SUPPORTED_PLATFORMS = frozenset({"bilibili", "zhihu", "douyin", "kuaishou"})
DAILYHOT_PATHS = {platform: platform for platform in SUPPORTED_PLATFORMS}
_SENSITIVE_KEY_PARTS = (
    "cookie", "token", "password", "secret", "authorization", "session", "credential",
    "storage_state", "local_storage", "indexeddb", "header", "proxy", "user_agent",
    "playwright", "cdp", "browser_context",
)
_PLATFORM_CONTENT_URLS = {
    "bilibili": (("bilibili.com", "b23.tv"), ("/video/", "/opus/", "/read/cv", "/")),
    "zhihu": (("zhihu.com",), ("/question/", "/p/")),
    "douyin": (("douyin.com",), ("/video/",)),
    "kuaishou": (("kuaishou.com",), ("/short-video/", "/photo/")),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _number(value: Any) -> int:
    try:
        return max(0, int(float(str(value).replace(",", "").strip())))
    except (TypeError, ValueError):
        return 0


def _url(value: Any) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _platform_bound_content_url(platform: str, value: Any) -> str:
    candidate = _url(value)
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    path = parsed.path or "/"
    hosts, paths = _PLATFORM_CONTENT_URLS.get(platform, ((), ()))
    if not (hosts and any(host == suffix or host.endswith("." + suffix) for suffix in hosts)):
        return ""
    return candidate if any(marker in path for marker in paths) else ""


def _parse_observed_at(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _content_id_from_url(value: Any) -> str:
    parsed = urlparse(_url(value))
    parts = [part for part in parsed.path.split("/") if part]
    return parts[-1][:120] if parts else ""


def _http_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "content-platform-hot-evidence/1.0"})
    with urlopen(request, timeout=15) as response:  # nosec B310 - HTTPS endpoint is explicit operator configuration
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("upstream response must be a JSON object")
    return payload


def _douyin_hot_http_json(url: str) -> dict[str, Any]:
    """Fetch the public web hot board with one stable browser-like request."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.douyin.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        },
    )
    with urlopen(request, timeout=15) as response:  # nosec B310 - fixed HTTPS public endpoint
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Douyin hot-board response must be a JSON object")
    return payload


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "data", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested_key in ("items", "data", "list"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [dict(row) for row in nested if isinstance(row, dict)]
    return []


def _base_row(*, platform: str, title: Any, canonical_url: Any, source: str, collector: str, signal_type: str, observed_at: str, raw_hash: str, rank: int = 0) -> dict[str, Any]:
    return {
        "version": "platform_hot_evidence_v1",
        "platform": platform,
        "title": str(title or "").strip(),
        "canonical_url": _url(canonical_url),
        "source": source,
        "collector": collector,
        "signal_type": signal_type,
        "evidence_level": "third_party_snapshot",
        "rank": rank,
        "observed_at": observed_at,
        "raw_response_hash": raw_hash,
        "license_status": "third_party_terms_unverified",
        "native_verified": False,
        "auto_selection_eligible": False,
        "research_only": False,
        "metrics": {},
    }


class DailyHotAdapter:
    """Normalize a self-hosted DailyHotApi response without promoting its proof level."""

    def __init__(self, base_url: str, *, fetch_json: JsonFetcher | None = None):
        self.base_url = str(base_url or "").rstrip("/")
        self.fetch_json = fetch_json or _http_json

    def collect(self, platforms: list[str] | tuple[str, ...]) -> dict[str, Any]:
        if not self.base_url:
            raise ValueError("dailyhot base_url is required; public demo endpoints are not implicit dependencies")
        observed_at, items, sources = _now(), [], []
        for platform in platforms:
            name = str(platform).casefold().strip()
            if name not in DAILYHOT_PATHS:
                sources.append({"source": "dailyhot", "platform": name, "status": "unsupported", "count": 0})
                continue
            url = f"{self.base_url}/{quote(DAILYHOT_PATHS[name])}"
            try:
                payload = self.fetch_json(url)
                raw_hash = _hash(payload)
                rows = _items(payload)
                for rank, raw in enumerate(rows, start=1):
                    title = raw.get("title") or raw.get("name") or raw.get("word")
                    if not str(title or "").strip():
                        continue
                    content_candidate = name == "bilibili" and bool(_url(raw.get("url") or raw.get("mobileUrl")))
                    row = _base_row(
                        platform=name,
                        title=title,
                        canonical_url=raw.get("url") or raw.get("mobileUrl"),
                        source="dailyhot_api",
                        collector="dailyhot_api",
                        signal_type="ranked_content_candidate" if content_candidate else "topic_signal",
                        observed_at=observed_at,
                        raw_hash=raw_hash,
                        rank=rank,
                    )
                    row["license_status"] = "DailyHotApi MIT; target-platform terms unverified"
                    row["upstream_updated_at"] = str(payload.get("updateTime") or payload.get("updatedTime") or "")
                    row["content_id"] = str(raw.get("id") or raw.get("bvid") or raw.get("sentence_id") or "")
                    if raw.get("author") or raw.get("owner"):
                        author = raw.get("author") or raw.get("owner")
                        row["author"] = author.get("name") if isinstance(author, dict) else str(author)
                    if raw.get("timestamp") or raw.get("pubdate"):
                        row["published_at"] = str(raw.get("timestamp") or raw.get("pubdate"))
                    heat = _number(raw.get("hot") if raw.get("hot") is not None else raw.get("hot_value"))
                    if name == "bilibili":
                        row["metrics"]["views"] = heat
                    else:
                        row["metrics"]["heat_value"] = heat
                    items.append(row)
                sources.append({"source": "dailyhot", "platform": name, "status": "ok", "count": len(rows), "endpoint": url, "raw_response_hash": raw_hash})
            except Exception as exc:  # preserve source failure as data; callers remain fail-closed
                sources.append({"source": "dailyhot", "platform": name, "status": "failed", "count": 0, "endpoint": url, "error": str(exc)[:240]})
        return {"version": "platform_hot_evidence_report_v1", "provider": "dailyhot", "observed_at": observed_at, "items": items, "sources": sources}


class BilibiliSearchAdapter:
    """Collect Bilibili's public first-party search results as work snapshots."""

    ENDPOINT = "https://api.bilibili.com/x/web-interface/search/all/v2"

    def __init__(self, *, fetch_json: JsonFetcher | None = None):
        self.fetch_json = fetch_json or _http_json

    def collect(
        self, *, queries: list[str] | tuple[str, ...], limit: int = 20,
        lane: str = "", order: str = "click",
    ) -> dict[str, Any]:
        observed_at = _now()
        normalized_lane = str(lane or "").casefold().strip()
        limit = max(1, min(int(limit), 50))
        items: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for query in [str(value).strip() for value in queries if str(value).strip()]:
            url = f"{self.ENDPOINT}?keyword={quote(query)}&page=1&page_size={limit}&order={quote(str(order or 'click'))}"
            try:
                payload = self.fetch_json(url)
                if int(payload.get("code", -1)) != 0:
                    raise ValueError(f"Bilibili search API returned code {payload.get('code')}")
                raw_hash = _hash(payload)
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                groups = data.get("result") if isinstance(data, dict) else []
                groups = groups if isinstance(groups, list) else []
                upstream: list[dict[str, Any]] = []
                for group in groups:
                    if not isinstance(group, dict) or group.get("result_type") != "video":
                        continue
                    upstream.extend(row for row in (group.get("data") or []) if isinstance(row, dict))
                accepted = 0
                for rank, raw in enumerate(upstream[:limit], start=1):
                    bvid = str(raw.get("bvid") or "").strip()
                    title = str(raw.get("title") or "").replace("<em class=\"keyword\">", "").replace("</em>", "").strip()
                    excerpt = str(raw.get("description") or "")[:500]
                    if not bvid or not title:
                        continue
                    positioning = None
                    if normalized_lane == "real_world_ai_implementation":
                        positioning = classify_discovery_text(title, excerpt)
                        if not positioning["accepted"]:
                            continue
                    row = _base_row(
                        platform="bilibili", title=title,
                        canonical_url=f"https://www.bilibili.com/video/{bvid}",
                        source="bilibili_search_api", collector="bilibili_search_api",
                        signal_type="search_content_candidate", observed_at=observed_at,
                        raw_hash=raw_hash, rank=rank,
                    )
                    row.update({
                        "evidence_level": "official_platform_search_snapshot",
                        "license_status": "Bilibili public search endpoint; observed work snapshot",
                        "content_id": bvid, "author": str(raw.get("author") or ""),
                        "author_id": str(raw.get("mid") or ""), "excerpt": excerpt,
                        "published_at": str(raw.get("pubdate") or ""), "query": query,
                        "native_verified": True, "generation_only": True,
                        "auto_selection_eligible": False,
                        "metrics": {"views": _number(raw.get("play")), "likes": _number(raw.get("like"))},
                    })
                    if normalized_lane:
                        row["lane"] = normalized_lane
                    if positioning:
                        row["positioning"] = positioning
                    row["evidence_triage"] = triage_real_world_ai_candidate(row)
                    items.append(row)
                    accepted += 1
                sources.append({
                    "source": "bilibili_search_api", "platform": "bilibili", "kind": "content_search",
                    "status": "ok", "count": accepted, "upstream_count": len(upstream),
                    "query": query, "endpoint": self.ENDPOINT, "raw_response_hash": raw_hash,
                })
            except Exception as exc:
                sources.append({
                    "source": "bilibili_search_api", "platform": "bilibili", "kind": "content_search",
                    "status": "failed", "count": 0, "query": query, "endpoint": self.ENDPOINT,
                    "error": str(exc)[:240],
                })
        return {"version": "platform_hot_evidence_report_v1", "provider": "bilibili_search_api", "observed_at": observed_at, "items": items, "sources": sources}


class BilibiliPopularAdapter:
    """Collect Bilibili's public first-party popular-work snapshot.

    Native work metrics are preserved as an observed snapshot, but the output is
    still generation-only because it has not passed same-lane relevance review.
    """

    ENDPOINT = "https://api.bilibili.com/x/web-interface/popular"

    def __init__(self, *, fetch_json: JsonFetcher | None = None):
        self.fetch_json = fetch_json or _http_json

    def collect(
        self,
        *,
        limit: int = 30,
        lane: str = "",
        lane_terms: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        url = f"{self.ENDPOINT}?ps={limit}&pn=1"
        observed_at = _now()
        try:
            payload = self.fetch_json(url)
            if int(payload.get("code", -1)) != 0:
                raise ValueError(f"Bilibili API returned code {payload.get('code')}")
            raw_hash = _hash(payload)
            data: dict[str, Any] = dict(payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}
            source_rows: list[Any] = list(data["list"]) if isinstance(data.get("list"), list) else []
            normalized_lane = str(lane or "").casefold().strip()
            normalized_terms = tuple(str(term).casefold().strip() for term in lane_terms if str(term).strip())
            if normalized_lane == "broad_ai" and not normalized_terms:
                normalized_terms = tuple(term.casefold() for term in AI_LANE_TERMS)
            items: list[dict[str, Any]] = []
            for rank, raw in enumerate(source_rows, start=1):
                if not isinstance(raw, dict):
                    continue
                bvid = str(raw.get("bvid") or "").strip()
                title = str(raw.get("title") or "").strip()
                if not bvid or not title:
                    continue
                lane_text = f"{title}\n{str(raw.get('desc') or '')}".casefold()
                positioning = None
                if normalized_lane == "real_world_ai_implementation":
                    positioning = classify_discovery_text(title, str(raw.get("desc") or ""))
                    if not positioning["accepted"]:
                        continue
                    lane_matches = list(positioning["ai_capability_terms"]) + list(positioning["scenario_terms"])
                else:
                    lane_matches = [term for term in normalized_terms if term in lane_text]
                    if normalized_terms and not lane_matches:
                        continue
                stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
                owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
                row = _base_row(
                    platform="bilibili",
                    title=title,
                    canonical_url=f"https://www.bilibili.com/video/{bvid}",
                    source="bilibili_popular_api",
                    collector="bilibili_popular_api",
                    signal_type="ranked_content_candidate",
                    observed_at=observed_at,
                    raw_hash=raw_hash,
                    rank=rank,
                )
                row.update({
                    "evidence_level": "official_platform_snapshot",
                    "license_status": "Bilibili public popular endpoint; observed snapshot",
                    "content_id": bvid,
                    "author": str(owner.get("name") or ""),
                    "author_id": str(owner.get("mid") or ""),
                    "excerpt": str(raw.get("desc") or "")[:500],
                    "published_at": str(raw.get("pubdate") or ""),
                    "native_verified": True,
                    "auto_selection_eligible": False,
                    "generation_only": True,
                    "metrics": {
                        "views": _number(stat.get("view")),
                        "likes": _number(stat.get("like")),
                        "coins": _number(stat.get("coin")),
                        "favorites": _number(stat.get("favorite")),
                        "comments": _number(stat.get("reply")),
                        "shares": _number(stat.get("share")),
                        "danmaku": _number(stat.get("danmaku")),
                    },
                })
                if normalized_lane:
                    row["lane"] = normalized_lane
                    row["lane_match_terms"] = lane_matches
                if positioning:
                    row["positioning"] = positioning
                items.append(row)
            return {"version": "platform_hot_evidence_report_v1", "provider": "bilibili_popular_api", "observed_at": observed_at, "items": items, "sources": [{"source": "bilibili_popular_api", "platform": "bilibili", "status": "ok", "count": len(items), "upstream_count": len(source_rows), "lane": normalized_lane, "endpoint": self.ENDPOINT, "raw_response_hash": raw_hash}]}
        except Exception as exc:
            return {"version": "platform_hot_evidence_report_v1", "provider": "bilibili_popular_api", "observed_at": observed_at, "items": [], "sources": [{"source": "bilibili_popular_api", "platform": "bilibili", "status": "failed", "count": 0, "endpoint": self.ENDPOINT, "error": str(exc)[:240]}]}


class DouyinHotPageAdapter:
    """Collect native Douyin hot topics, never individual video performance."""

    ENDPOINT = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
    PAGE_URL = "https://www.douyin.com/hot"

    def __init__(self, *, fetch_json: JsonFetcher | None = None):
        self.fetch_json = fetch_json or _douyin_hot_http_json

    def collect(self, *, limit: int = 50, lane: str = "", lane_terms: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
        observed_at = _now()
        normalized_lane = str(lane or "").casefold().strip()
        normalized_terms = tuple(str(term).casefold().strip() for term in lane_terms if str(term).strip())
        if normalized_lane == "broad_ai" and not normalized_terms:
            normalized_terms = tuple(term.casefold() for term in AI_LANE_TERMS)
        try:
            payload = self.fetch_json(self.ENDPOINT)
            raw_hash = _hash(payload)
            data = payload.get("data") if isinstance(payload, dict) else {}
            source_rows = data.get("word_list") if isinstance(data, dict) else []
            source_rows = source_rows if isinstance(source_rows, list) else []
            items: list[dict[str, Any]] = []
            for rank, raw in enumerate(source_rows[:max(1, min(int(limit), 50))], start=1):
                if not isinstance(raw, dict):
                    continue
                title = str(raw.get("word") or "").strip()
                if not title:
                    continue
                positioning = None
                if normalized_lane == "real_world_ai_implementation":
                    positioning = classify_discovery_text(title)
                    if not positioning["accepted"]:
                        continue
                    lane_matches = list(positioning["ai_capability_terms"]) + list(positioning["scenario_terms"])
                else:
                    lane_matches = [term for term in normalized_terms if term in title.casefold()]
                    if normalized_terms and not lane_matches:
                        continue
                row = _base_row(platform="douyin", title=title, canonical_url="", source="douyin_public_hot_page", collector="douyin_public_hot_page", signal_type="topic_signal", observed_at=observed_at, raw_hash=raw_hash, rank=rank)
                row.update({
                    "evidence_level": "official_platform_snapshot_e1",
                    "evidence_grade": "E1_topic_board",
                    "source_record_id": f"hot:{rank}:{hashlib.sha256(title.encode('utf-8')).hexdigest()[:16]}",
                    "source_page_url": self.PAGE_URL,
                    "topic_url": _url(raw.get("url")),
                    "raw_item_excerpt": f"{rank}. {title} | heat={raw.get('hot_value')}",
                    "license_status": "Douyin public hot page; observed topic snapshot subject to applicable terms",
                    "native_verified": True,
                    "generation_only": True,
                    "auto_selection_eligible": False,
                    "fusion_eligible": False,
                    "metrics": {"heat_value": _number(raw.get("hot_value"))},
                    "heat_display": str(raw.get("hot_value") or ""),
                })
                if raw.get("label") not in (None, ""):
                    row["label"] = str(raw.get("label"))[:80]
                if normalized_lane:
                    row["lane"] = normalized_lane
                    row["lane_match_terms"] = lane_matches
                if positioning:
                    row["positioning"] = positioning
                items.append(row)
            return {"version": "platform_hot_evidence_report_v1", "provider": "douyin_public_hot_page", "observed_at": observed_at, "items": items, "sources": [{"source": "douyin_public_hot_page", "platform": "douyin", "status": "ok", "count": len(items), "upstream_count": len(source_rows), "lane": normalized_lane, "endpoint": self.ENDPOINT, "page_url": self.PAGE_URL, "raw_response_hash": raw_hash}]}
        except Exception as exc:
            return {"version": "platform_hot_evidence_report_v1", "provider": "douyin_public_hot_page", "observed_at": observed_at, "items": [], "sources": [{"source": "douyin_public_hot_page", "platform": "douyin", "status": "failed", "count": 0, "endpoint": self.ENDPOINT, "page_url": self.PAGE_URL, "error": str(exc)[:240]}]}


class ZhihuOpenHotAdapter:
    """Import official Zhihu hot/search snapshots without changing selection gates."""

    def __init__(self, *, client: Any | None = None):
        if client is None:
            from .zhihu_open_adapter import ZhihuOpenAdapter

            client = ZhihuOpenAdapter()
        self.client = client

    def collect(self, *, queries: list[str] | tuple[str, ...] = (), hot_limit: int = 30, search_limit: int = 10) -> dict[str, Any]:
        observed_at, items, sources = _now(), [], []
        try:
            trending = self.client.trending(limit=max(1, min(int(hot_limit), 30)))
            raw_hash = _hash(trending)
            for index, raw in enumerate(trending, start=1):
                title, url = str(raw.get("title") or "").strip(), _platform_bound_content_url("zhihu", raw.get("url"))
                positioning = classify_discovery_text(title)
                if not title or not url or not positioning["accepted"]:
                    continue
                row = _base_row(platform="zhihu", title=title, canonical_url=url, source="zhihu_open_platform", collector="zhihu_open_platform", signal_type="topic_signal", observed_at=observed_at, raw_hash=raw_hash, rank=_number((raw.get("metric") or {}).get("rank")) or index)
                row.update({"generation_only": True, "evidence_level": "official_platform_snapshot", "license_status": "Zhihu Open Platform terms; generation-only snapshot", "content_id": _content_id_from_url(url), "source_record_id": f"hot:{index}", "metrics": {"hot_score": _number(raw.get("points"))}, "positioning": positioning})
                row["evidence_triage"] = triage_real_world_ai_candidate(row)
                items.append(row)
            sources.append({"source": "zhihu_open_platform", "kind": "hot_list", "platform": "zhihu", "status": "ok", "count": len(trending), "raw_response_hash": raw_hash})
        except Exception as exc:
            sources.append({"source": "zhihu_open_platform", "kind": "hot_list", "platform": "zhihu", "status": "failed", "count": 0, "error": str(exc)[:240]})
        for query in (str(value).strip() for value in queries):
            if not query:
                continue
            try:
                results = self.client.search(query, limit=max(1, min(int(search_limit), 20)), scope="zhihu")
                raw_hash = _hash({"query": query, "items": results})
                count = 0
                for index, raw in enumerate(results, start=1):
                    title, url = str(raw.get("title") or "").strip(), _platform_bound_content_url("zhihu", raw.get("url"))
                    excerpt = str(raw.get("content_excerpt") or "")[:500]
                    positioning = classify_discovery_text(title, excerpt)
                    if not title or not url or not positioning["accepted"]:
                        continue
                    # Search records with a canonical work URL, stable content ID
                    # and visible work-level counters are public-work snapshots;
                    # they remain generation-only, never viral/automation proof.
                    row = _base_row(platform="zhihu", title=title, canonical_url=url, source="zhihu_open_platform", collector="zhihu_open_platform", signal_type="public_work_metadata_snapshot", observed_at=observed_at, raw_hash=raw_hash, rank=index)
                    row.update({"generation_only": True, "evidence_level": "official_platform_search_snapshot", "license_status": "Zhihu Open Platform terms; generation-only snapshot", "content_id": _content_id_from_url(url), "source_record_id": f"search:{index}", "query": query, "content_type": str(raw.get("type") or ""), "author": str(raw.get("author") or ""), "excerpt": excerpt, "metrics": {"likes": _number(raw.get("points")), "comments": _number(raw.get("comment_count"))}, "positioning": positioning})
                    row["evidence_triage"] = triage_real_world_ai_candidate(row)
                    items.append(row)
                    count += 1
                sources.append({"source": "zhihu_open_platform", "kind": "content_search", "platform": "zhihu", "status": "ok", "query": query, "count": count, "raw_response_hash": raw_hash})
            except Exception as exc:
                sources.append({"source": "zhihu_open_platform", "kind": "content_search", "platform": "zhihu", "status": "failed", "query": query, "count": 0, "error": str(exc)[:240]})
        return {"version": "platform_hot_evidence_report_v1", "provider": "zhihu_open_platform", "observed_at": observed_at, "items": items, "sources": sources}


def _reject_sensitive_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(part in str(key).casefold() for part in _SENSITIVE_KEY_PARTS):
                raise ValueError("sensitive credential-like key found in MediaCrawler research import")
            _reject_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_keys(nested)


def _research_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    direct = payload.get("items") or payload.get("data") or payload.get("contents")
    if isinstance(direct, list):
        return [dict(row) for row in direct if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for platform in SUPPORTED_PLATFORMS:
        value = payload.get(platform)
        if isinstance(value, list):
            rows.extend({**dict(row), "platform": str(row.get("platform") or platform)} for row in value if isinstance(row, dict))
    return rows


def import_mediacrawler_research(path: str | Path) -> dict[str, Any]:
    """Import a manually produced, non-commercial research export; never run the crawler."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("version") == "platform_research_export_v1":
        raise ValueError("automatic platform research export is not a MediaCrawler research import")
    _reject_sensitive_keys(payload)
    imported_at, raw_hash, items, rejected = _now(), _hash(payload), [], []
    for raw in _research_rows(payload):
        platform = str(raw.get("platform") or "").casefold().strip()
        title = str(raw.get("title") or raw.get("desc") or "").strip()
        canonical_url = raw.get("content_url") or raw.get("url") or raw.get("video_url") or raw.get("note_url")
        content_id = str(raw.get("content_id") or raw.get("video_id") or raw.get("aweme_id") or raw.get("bv_id") or raw.get("note_id") or raw.get("photo_id") or raw.get("work_id") or "").strip()
        observed_at = _parse_observed_at(raw.get("collected_at") or raw.get("observed_at") or raw.get("captured_at"))
        source_record_id = str(raw.get("source_record_id") or raw.get("record_id") or raw.get("item_id") or "").strip()
        query = str(raw.get("query") or raw.get("search_query") or raw.get("query_term") or "").strip()
        bound_url = _platform_bound_content_url(platform, canonical_url)
        if platform not in SUPPORTED_PLATFORMS or not title:
            continue
        missing = [name for name, value in (("content_id", content_id), ("observed_at", observed_at), ("source_record_id", source_record_id), ("query", query)) if not value]
        if missing:
            rejected.append(f"traceability missing: {', '.join(missing)}")
            continue
        if not bound_url:
            rejected.append("platform-bound URL required")
            continue
        row = _base_row(platform=platform, title=title, canonical_url=bound_url, source="mediacrawler_research_import", collector="mediacrawler_research_import", signal_type="research_content_snapshot", observed_at=observed_at, raw_hash=raw_hash)
        row["research_only"] = True
        row["license_status"] = "MediaCrawler NON-COMMERCIAL LEARNING LICENSE 1.1; research-only import"
        row["evidence_level"] = "research_import_unverified"
        row["content_id"] = content_id
        row["source_record_id"] = source_record_id[:160]
        row["query"] = query[:300]
        row["imported_at"] = imported_at
        row["author"] = str(raw.get("author") or raw.get("nickname") or "")
        row["published_at"] = str(raw.get("publish_time") or raw.get("created_time") or raw.get("timestamp") or "")
        metric_map = {
            "views": ("video_play_count", "view_count", "play_count", "viewCount"),
            "likes": ("liked_count", "like_count", "realLikeCount"),
            "comments": ("comment_count",),
            "shares": ("share_count", "video_share_count"),
            "favorites": ("favorite_count", "video_favorite_count", "collected_count"),
            "coins": ("coin_count", "video_coin_count"),
        }
        for target, aliases in metric_map.items():
            for key in aliases:
                if raw.get(key) is not None:
                    row["metrics"][target] = _number(raw[key])
                    break
        items.append(row)
    if rejected:
        raise ValueError(f"MediaCrawler research import rejected for platform-bound traceability: {rejected[0]}")
    return {"version": "platform_hot_evidence_report_v1", "provider": "mediacrawler_research_import", "observed_at": imported_at, "research_only": True, "items": items, "sources": [{"source": "mediacrawler_research_import", "status": "ok", "count": len(items), "path": str(source), "raw_response_hash": raw_hash}]}


def collect_platform_hot_evidence(config: dict[str, Any], *, fetch_json: JsonFetcher | None = None) -> dict[str, Any]:
    """Collect configured third-party snapshots into a single, non-promotional report."""
    config = dict(config or {})
    policy = load_real_world_ai_positioning()
    requested_profile = str(config.get("query_policy_profile") or "").strip()
    if requested_profile:
        if requested_profile != policy["policy_profile"]:
            raise ValueError("hot evidence query policy profile does not match the canonical AI lane")
        queries = build_discovery_queries(
            seed=str(config.get("query_seed") or "") or None,
            language=str(config.get("query_language") or "zh"),
        )
        for section in ("bilibili_search", "zhihu_open"):
            if section in config:
                config[section] = {**dict(config.get(section) or {}), "queries": queries}
    platforms = [str(value).casefold().strip() for value in config.get("platforms", sorted(SUPPORTED_PLATFORMS))]
    reports: list[dict[str, Any]] = []
    dailyhot = dict(config.get("dailyhot") or {})
    if dailyhot.get("enabled"):
        reports.append(DailyHotAdapter(str(dailyhot.get("base_url") or ""), fetch_json=fetch_json).collect(platforms))
    public_metadata = dict(config.get("public_work_metadata") or {})
    for platform, urls in public_metadata.items():
        if str(platform).casefold() not in {"youtube", "tiktok","kuaishou"}:
            continue
        options={}
        if str(platform).casefold()=='kuaishou':
            if not isinstance(urls,dict):raise ValueError('kuaishou_authorized_export_config_required')
            options={key:urls[key] for key in ('raw_responses','source_trust','max_age_seconds','authorization_reference','license_scope') if key in urls}
            urls=urls.get('urls') or []
        reports.append(PublicWorkMetadataAdapter().collect(
            platform=str(platform).casefold(),
            urls=[str(value) for value in (urls or [])],
            **options,
        ))
    bilibili_search = dict(config.get("bilibili_search") or {})
    if bilibili_search.get("enabled"):
        reports.append(BilibiliSearchAdapter(fetch_json=fetch_json).collect(
            queries=[str(value) for value in (bilibili_search.get("queries") or [])],
            limit=int(bilibili_search.get("limit") or 20),
            lane=str(bilibili_search.get("lane") or ""),
            order=str(bilibili_search.get("order") or "click"),
        ))
    bilibili_popular = dict(config.get("bilibili_popular") or {})
    if bilibili_popular.get("enabled"):
        reports.append(BilibiliPopularAdapter(fetch_json=fetch_json).collect(
            limit=int(bilibili_popular.get("limit") or 30),
            lane=str(bilibili_popular.get("lane") or ""),
            lane_terms=[str(value) for value in (bilibili_popular.get("lane_terms") or [])],
        ))
    douyin_hot_page = dict(config.get("douyin_hot_page") or {})
    if douyin_hot_page.get("enabled"):
        reports.append(DouyinHotPageAdapter(fetch_json=fetch_json).collect(
            limit=int(douyin_hot_page.get("limit") or 50),
            lane=str(douyin_hot_page.get("lane") or ""),
            lane_terms=[str(value) for value in (douyin_hot_page.get("lane_terms") or [])],
        ))
    zhihu_open = dict(config.get("zhihu_open") or {})
    if zhihu_open.get("enabled"):
        reports.append(ZhihuOpenHotAdapter().collect(
            queries=[str(value) for value in (zhihu_open.get("queries") or [])],
            hot_limit=int(zhihu_open.get("hot_limit") or 30),
            search_limit=int(zhihu_open.get("search_limit") or 10),
        ))
    twitter_browser = dict(config.get("twitter_native_browser") or {})
    if twitter_browser.get("enabled"):
        from .twitter_native_source import TwitterNativeBrowserAdapter
        reports.append(TwitterNativeBrowserAdapter().collect(twitter_browser))
    mediacrawler = dict(config.get("mediacrawler") or {})
    if mediacrawler.get("enabled"):
        if not mediacrawler.get("research_only"):
            raise ValueError("MediaCrawler integration requires research_only=true")
        reports.append(import_mediacrawler_research(str(mediacrawler.get("import_path") or "")))
    bundle = {
        "version": "platform_hot_evidence_bundle_v1",
        "policy_profile": policy["policy_profile"],
        "policy_revision": policy["policy_revision"],
        "observed_at": _now(),
        "auto_selection_eligible": False,
        "reports": reports,
        "items": [item for report in reports for item in report.get("items", [])],
        "sources": [source for report in reports for source in report.get("sources", [])],
    }
    bundle["fusion"] = fuse_platform_hot_evidence(bundle)
    return bundle


def build_platform_research_export(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build a redacted review artifact; it is never a fusion input or crawler import."""
    if not isinstance(bundle, dict) or bundle.get("version") != "platform_hot_evidence_bundle_v1":
        raise ValueError("platform research export requires platform_hot_evidence_bundle_v1")
    rows = bundle.get("items")
    if not isinstance(rows, list):
        raise ValueError("platform research export requires an items list")
    output: list[dict[str, Any]] = []
    metric_keys = ("views", "likes", "comments", "shares", "favorites", "heat_value", "hot_score")
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").casefold().strip()
        title = str(raw.get("title") or "").strip()
        observed_at = _parse_observed_at(raw.get("observed_at"))
        source = str(raw.get("source") or "").casefold().strip()
        collector = str(raw.get("collector") or "").casefold().strip()
        raw_hash = str(raw.get("raw_response_hash") or "").strip()
        if platform not in SUPPORTED_PLATFORMS or not all((title, observed_at, source, collector, raw_hash)):
            continue
        canonical_url = _platform_bound_content_url(platform, raw.get("canonical_url"))
        content_id = str(raw.get("content_id") or _content_id_from_url(canonical_url) or "").strip()[:120]
        official_search_content = source == "zhihu_open_platform" and bool(raw.get("content_type")) and bool(canonical_url)
        is_content = bool(canonical_url and content_id and (raw.get("signal_type") == "ranked_content_candidate" or official_search_content))
        metrics = dict(raw.get("metrics") or {}) if isinstance(raw.get("metrics"), dict) else {}
        item = {
            "platform": platform,
            "research_kind": "content_snapshot" if is_content else "topic_signal_snapshot",
            "title": title[:200],
            "observed_at": observed_at,
            "source": source,
            "collector": collector,
            "source_record_id": str(raw.get("source_record_id") or f"{collector}:{index}")[:160],
            "source_record_hash": raw_hash,
            "rank": _number(raw.get("rank")),
            "metrics": {key: _number(metrics[key]) for key in metric_keys if metrics.get(key) is not None},
            "research_only": True,
            "generation_only": True,
            "native_verified": False,
            "auto_selection_eligible": False,
            "fusion_eligible": False,
            "mediacrawler_import_eligible": False,
        }
        if is_content:
            item["content_id"] = content_id
            item["content_url"] = canonical_url
        if source == "zhihu_open_platform":
            item.update({
                "query": str(raw.get("query") or "")[:300],
                "content_type": str(raw.get("content_type") or "")[:80],
                "author": str(raw.get("author") or "")[:120],
                "excerpt": str(raw.get("excerpt") or "")[:500],
            })
        output.append(item)
    return {
        "version": "platform_research_export_v1",
        "generated_at": _now(),
        "source_bundle_hash": _hash({"version": bundle.get("version"), "items": rows}),
        "usage": {
            "research_only": True,
            "generation_only": True,
            "fusion_eligible": False,
            "mediacrawler_import_eligible": False,
            "auto_selection_eligible": False,
        },
        "items": output,
    }


def write_platform_research_export(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_platform_research_export(report), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def write_hot_evidence_snapshot(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target
