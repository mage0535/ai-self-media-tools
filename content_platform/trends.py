import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .paths import project_home, trend_cache_dir


def normalize_topic(title):
    return " ".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(title).casefold()))


def rank_trends(items, profile=None, used=None, limit=10, learned=None):
    profile, used = profile or {}, {normalize_topic(item) for item in (used or set())}
    learned = learned or {}
    keywords = [str(word).casefold() for word in profile.get("keywords", [])]
    source_weights = profile.get("source_weights", {})
    banned = [str(word).casefold() for word in profile.get("banned_topics", [])]
    preferred_sources = learned.get("preferred_sources", {})
    preferred_clusters = learned.get("preferred_clusters", [])
    unique = {}
    for item in items:
        title = str(item.get("title", "")).strip()
        normalized = normalize_topic(title)
        if not normalized or normalized in used or any(word in title.casefold() for word in banned):
            continue
        source_score = float(source_weights.get(item.get("source", ""), 0))
        fit_score = sum(3 for word in keywords if word in title.casefold())
        learned_source_score = float(preferred_sources.get(item.get("source", ""), 0))
        learned_cluster_score = 0.0
        for cluster in preferred_clusters:
            if str(cluster.get("label", "")).casefold() in title.casefold():
                learned_cluster_score = max(learned_cluster_score, float(cluster.get("weight", 0)))
            for signal in cluster.get("topic_signals", []):
                if str(signal).casefold() in title.casefold():
                    learned_cluster_score = max(learned_cluster_score, float(cluster.get("weight", 0)))
        if source_score <= 0 and fit_score <= 0:
            continue
        score = source_score + fit_score + learned_source_score + learned_cluster_score
        score += math.log1p(max(0, float(item.get("points", 0) or 0))) / 4
        stage = "emerging"
        points = max(0, float(item.get("points", 0) or 0))
        if points >= 150 or score >= 7:
            stage = "viral_candidate"
        elif points >= 40 or score >= 4:
            stage = "hot"
        angle = "方法拆解"
        if stage == "viral_candidate":
            angle = "爆款信号解读"
        elif stage == "hot":
            angle = "热点深度分析"
        candidate = {
            **item,
            "score": round(score, 3),
            "fingerprint": normalized,
            "trend_stage": stage,
            "trend_angle": angle,
            "learned_source_score": round(learned_source_score, 3),
            "learned_cluster_score": round(learned_cluster_score, 3),
        }
        if normalized not in unique or candidate["score"] > unique[normalized]["score"]:
            unique[normalized] = candidate
    ranked = sorted(unique.values(), key=lambda row: (-row["score"], row["title"]))
    relevant = [row for row in ranked if row["score"] > 0]
    selected, source_counts = [], {}
    while relevant and len(selected) < int(limit):
        relevant.sort(key=lambda row: (source_counts.get(row.get("source", ""), 0), -row["score"]))
        item = relevant.pop(0)
        selected.append(item)
        source = item.get("source", "")
        source_counts[source] = source_counts.get(source, 0) + 1
    return selected


class TrendCollector:
    def __init__(self, config=None):
        self.config = config or {}

    def collect(self, refresh=False):
        report = self.collect_with_report(refresh=refresh)
        return report["items"]

    def collect_with_report(self, refresh=False):
        started_all = time.time()
        max_total_seconds = float(self.config.get("max_total_seconds", 45))
        sources = []
        items = []
        reddit_items = []
        reddit_cfg = self.config.get("reddit", {})
        if reddit_cfg.get("enabled"):
            started = time.time()
            try:
                reddit_items = RedditTrendCollector(reddit_cfg).collect()
                sources.append(_source_report("reddit", "ok" if reddit_items else "empty", len(reddit_items), started))
            except Exception as exc:  # noqa: BLE001 - source failures must be reported, not hidden.
                reddit_items = []
                sources.append(_source_report("reddit", "failed", 0, started, str(exc)[:240]))
        for source_name, source_cfg in self._direct_sources().items():
            if time.time() - started_all >= max_total_seconds:
                sources.append(_source_report(source_name, "skipped", 0, time.time(), "trend collection time budget exhausted"))
                continue
            started = time.time()
            try:
                source_items = DirectTrendSource(source_name, source_cfg).collect()
                items.extend(source_items)
                if source_items and all(row.get("source_unavailable") for row in source_items):
                    status = "degraded"
                else:
                    status = "ok" if source_items else "empty"
                sources.append(_source_report(source_name, status, len(source_items), started))
            except Exception as exc:  # noqa: BLE001
                sources.append(_source_report(source_name, "failed", 0, started, str(exc)[:240]))
        data_dir = Path(self.config.get("legacy_data_dir", str(trend_cache_dir())))
        legacy_items = []
        if refresh:
            script = Path(self.config.get("legacy_script", str(project_home() / "external" / "scripts" / "trend_collector.py")))
            if script.is_file():
                started = time.time()
                try:
                    proc = subprocess.run(
                        ["python3", str(script)],
                        capture_output=True,
                        text=True,
                        timeout=int(self.config.get("legacy_timeout", 20)),
                        check=False,
                    )
                    if proc.returncode != 0:
                        sources.append(_source_report("legacy_script", "failed", 0, started, (proc.stderr or proc.stdout)[-240:]))
                    else:
                        sources.append(_source_report("legacy_script", "ok", 0, started))
                except subprocess.TimeoutExpired:
                    sources.append(_source_report("legacy_script", "failed", 0, started, "legacy trend script timed out"))
        files = sorted(data_dir.glob("trending_*.json"), reverse=True)
        if files:
            started = time.time()
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("trends", payload.get("items", []))
            legacy_items = self._normalize_rows(rows, "legacy_cache")
            sources.append(_source_report("legacy_cache", "ok" if legacy_items else "empty", len(legacy_items), started, metadata={"file": str(files[0])}))
        items.extend(legacy_items)
        items.extend(reddit_items)
        deduped = self._dedupe(items)
        fallback_used = False
        if not deduped and self.config.get("fallback_enabled"):
            fallback_used = True
            deduped = self._fallback_items()
            sources.append(_source_report("fallback", "ok", len(deduped), time.time()))
        return {
            "items": deduped,
            "sources": sources,
            "summary": {
                "total_sources": len(sources),
                "ok_sources": sum(1 for row in sources if row.get("status") == "ok"),
                "failed_sources": sum(1 for row in sources if row.get("status") == "failed"),
                "degraded_sources": sum(1 for row in sources if row.get("status") == "degraded"),
                "empty_sources": sum(1 for row in sources if row.get("status") == "empty"),
                "skipped_sources": sum(1 for row in sources if row.get("status") == "skipped"),
                "items": len(deduped),
                "fallback_used": fallback_used,
            },
        }

    def _direct_sources(self):
        configured = self.config.get("direct_sources", {})
        if configured is False:
            return {}
        defaults = {
            "hackernews": {"enabled": True, "limit": 20, "timeout": 8},
            "github": {"enabled": True, "limit": 20, "timeout": 8, "query": "AI workflow automation content operations"},
            "bilibili": {"enabled": True, "limit": 20, "timeout": 8},
            "zhihu": {"enabled": True, "limit": 20, "timeout": 8, "query": "AI \u5de5\u5177 \u6548\u7387 \u5de5\u4f5c\u6d41 site:zhihu.com"},
            "douyin": {"enabled": True, "limit": 20, "timeout": 8, "query": "AI \u5de5\u5177 \u6548\u7387 \u77ed\u89c6\u9891 \u6296\u97f3"},
            "wewrite_hotspots": {"enabled": False, "limit": 20, "timeout": 8},
        }
        if isinstance(configured, dict):
            for name, value in configured.items():
                if isinstance(value, dict):
                    defaults[name] = {**defaults.get(name, {}), **value}
                else:
                    defaults[name] = {"enabled": bool(value)}
        return {name: cfg for name, cfg in defaults.items() if cfg.get("enabled", True)}

    @staticmethod
    def _normalize_rows(rows, default_source):
        seen, result = set(), []
        for row in rows:
            if isinstance(row, str):
                row = {"title": row}
            title = str(row.get("title", "")).strip()
            key = title.casefold()
            if title and key not in seen:
                seen.add(key)
                result.append({**row, "title": title, "source": row.get("source", default_source), "url": row.get("url", "")})
        return result

    @staticmethod
    def _dedupe(rows):
        seen, result = set(), []
        for item in rows:
            title = str(item.get("title", "")).strip()
            key = title.casefold()
            if title and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _fallback_items(self):
        raw_keywords = self.config.get("fallback_keywords")
        if not raw_keywords:
            raw_keywords = self.config.get("keywords")
        if isinstance(raw_keywords, dict):
            keywords = []
            for value in raw_keywords.values():
                if isinstance(value, list):
                    keywords.extend(value)
        elif isinstance(raw_keywords, list):
            keywords = raw_keywords
        else:
            keywords = []
        cleaned = [str(item).strip() for item in keywords if str(item).strip()]
        if not cleaned:
            cleaned = ["AI workflow automation", "content operations", "short video repurposing"]
        result = []
        for index, keyword in enumerate(cleaned[:10]):
            title = f"{keyword}: practical workflow opportunity"
            result.append({
                "title": title,
                "source": "fallback",
                "url": "",
                "points": max(1, len(keywords) - index),
                "fallback": True,
            })
        return result


def _source_report(name, status, count, started, error="", metadata=None):
    report = {
        "source": name,
        "status": status,
        "count": int(count),
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    if error:
        report["error"] = error
    if metadata:
        report["metadata"] = metadata
    return report


class DirectTrendSource:
    """Small no-browser trend collectors used before falling back to Hermes tools."""

    def __init__(self, name, config=None):
        self.name = str(name).casefold()
        self.config = config or {}
        self.limit = int(self.config.get("limit", 20))
        self.timeout = int(self.config.get("timeout", 15))

    def collect(self):
        if self.name == "hackernews":
            return self._hackernews()
        if self.name == "github":
            return self._github()
        if self.name == "bilibili":
            return self._bilibili()
        if self.name == "zhihu":
            return self._web_search_source("zhihu", "AI 工具 效率 工作流 site:zhihu.com")
        if self.name == "douyin":
            return self._web_search_source("douyin", "AI 工具 效率 短视频 抖音")
        if self.name == "wewrite_hotspots":
            return self._wewrite_hotspots()
        raise ValueError(f"unknown direct trend source: {self.name}")

    def _request_json(self, url, headers=None):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.config.get("user_agent", "ai-self-media-tools/1.0.0 trend collector"),
                **(headers or {}),
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def _hackernews(self):
        payload = self._request_json("https://hn.algolia.com/api/v1/search?tags=front_page")
        items = []
        for row in payload.get("hits", [])[: self.limit]:
            title = str(row.get("title") or row.get("story_title") or "").strip()
            if not title:
                continue
            items.append({
                "title": title,
                "source": "hackernews",
                "url": row.get("url") or f"https://news.ycombinator.com/item?id={row.get('objectID')}",
                "points": int(row.get("points") or 0),
                "comments": int(row.get("num_comments") or 0),
            })
        return items

    def _wewrite_hotspots(self):
        binary = os.path.expanduser(str(self.config.get("wewrite_bin") or shutil.which("wewrite") or "~/.local/bin/wewrite"))
        if not Path(binary).is_file():
            raise RuntimeError(f"wewrite CLI not found: {binary}")
        proc = subprocess.run(
            [binary, "hotspots", "--limit", str(self.limit)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "wewrite hotspots failed")[:240])
        payload = json.loads(proc.stdout or "[]")
        rows = payload if isinstance(payload, list) else payload.get("items", payload.get("hotspots", []))
        items = []
        for row in rows[: self.limit]:
            if isinstance(row, str):
                row = {"title": row}
            title = str(row.get("title") or row.get("topic") or row.get("keyword") or "").strip()
            if not title:
                continue
            items.append({
                **row,
                "title": title,
                "source": row.get("source", "wewrite_hotspots"),
                "url": row.get("url", ""),
                "points": int(row.get("points") or row.get("score") or row.get("heat") or 0),
            })
        return items

    def _github(self):
        since = (datetime.now(timezone.utc) - timedelta(days=int(self.config.get("days", 14)))).date().isoformat()
        query = str(self.config.get("query") or "AI workflow automation")
        q = urllib.parse.urlencode({
            "q": f"{query} created:>={since}",
            "sort": "stars",
            "order": "desc",
            "per_page": min(self.limit, 50),
        })
        payload = self._request_json(f"https://api.github.com/search/repositories?{q}")
        items = []
        for row in payload.get("items", [])[: self.limit]:
            name = str(row.get("full_name") or row.get("name") or "").strip()
            desc = str(row.get("description") or "").strip()
            if not name:
                continue
            items.append({
                "title": f"{name}: {desc}" if desc else name,
                "source": "github",
                "url": row.get("html_url", ""),
                "points": int(row.get("stargazers_count") or 0),
                "language": row.get("language"),
            })
        return items

    def _bilibili(self):
        try:
            payload = self._request_json(f"https://api.bilibili.com/x/web-interface/popular?ps={min(self.limit, 50)}&pn=1")
        except Exception:
            return self._web_search_source("bilibili", "AI 工具 效率 工作流 site:bilibili.com")
        rows = payload.get("data", {}).get("list", [])
        items = []
        for row in rows[: self.limit]:
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            stat = row.get("stat") or {}
            items.append({
                "title": title,
                "source": "bilibili",
                "url": row.get("short_link_v2") or row.get("short_link") or row.get("uri", ""),
                "points": int(stat.get("view") or 0) + int(stat.get("like") or 0) * 2 + int(stat.get("danmaku") or 0),
                "author": (row.get("owner") or {}).get("name", ""),
            })
        return items

    def _web_search_source(self, source, default_query):
        query = str(self.config.get("query") or default_query)
        for collector in (self._searxng_search, self._duckduckgo_html_search, self._bing_html_search, self._baidu_html_search):
            items = collector(source, query)
            if items:
                return items
        if self.config.get("source_fallback_enabled", True):
            return self._source_fallback_items(source, query)
        return []

    def _searxng_search(self, source, query):
        base = str(self.config.get("searxng_url") or os.environ.get("SEARXNG_URL") or os.environ.get("SEARXNG_BASE_URL") or "").rstrip("/")
        if not base:
            return []
        url = base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json", "language": "zh-CN"})
        try:
            payload = self._request_json(url, headers={"Accept": "application/json"})
        except Exception:
            return []
        rows = payload.get("results") or []
        return self._search_rows_to_items(source, rows)

    def _duckduckgo_html_search(self, source, query):
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.get("user_agent", "Mozilla/5.0 ai-self-media-tools trend collector"),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                html = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return []
        rows = []
        for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
            url = urllib.parse.unquote(re.sub(r"&amp;", "&", match.group(1)))
            title = re.sub(r"<[^>]+>", "", match.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                rows.append({"title": title, "url": url})
            if len(rows) >= self.limit:
                break
        return self._search_rows_to_items(source, rows)

    def _bing_html_search(self, source, query):
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "zh-CN"})
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.get("user_agent", "Mozilla/5.0 ai-self-media-tools trend collector"),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                html = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return []
        rows = []
        for match in re.finditer(r'<li class="b_algo"[\s\S]*?<a href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I):
            title = re.sub(r"<[^>]+>", "", match.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                rows.append({"title": title, "url": match.group(1)})
            if len(rows) >= self.limit:
                break
        return self._search_rows_to_items(source, rows)

    def _baidu_html_search(self, source, query):
        url = "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query})
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.get("user_agent", "Mozilla/5.0 ai-self-media-tools trend collector"),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                html = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return []
        rows = []
        for match in re.finditer(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
            title = re.sub(r"<[^>]+>", "", match.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                rows.append({"title": title, "url": match.group(1)})
            if len(rows) >= self.limit:
                break
        return self._search_rows_to_items(source, rows)

    def _search_rows_to_items(self, source, rows):
        items = []
        for row in rows[: self.limit]:
            if isinstance(row, str):
                row = {"title": row}
            title = str(row.get("title") or row.get("content") or "").strip()
            if not title:
                continue
            items.append({
                "title": title,
                "source": f"{source}:web_search",
                "url": row.get("url", ""),
                "points": int(row.get("score") or row.get("points") or 1),
                "fallback_source": True,
            })
        return items

    def _source_fallback_items(self, source, query):
        keywords = [item for item in re.split(r"\s+", query) if item and not item.startswith("site:")]
        if not keywords:
            keywords = [source, "AI", "workflow"]
        templates = [
            "{source} 平台近期围绕 {topic} 的账号增长观察",
            "{source} 用户讨论 {topic} 时最常见的痛点和反对意见",
            "{source} 适合测试的 {topic} 选题切口",
        ]
        topic = " ".join(keywords[:4])
        return [
            {
                "title": template.format(source=source, topic=topic),
                "source": f"{source}:source_fallback",
                "url": "",
                "points": max(1, len(templates) - index),
                "fallback_source": True,
                "source_unavailable": True,
                "query": query,
                "warning": "live platform/search source unavailable; use only as a temporary operating hypothesis",
            }
            for index, template in enumerate(templates)
        ][: self.limit]


class RedditTrendCollector:
    API_ROOT = "https://oauth.reddit.com"

    def __init__(self, config=None):
        self.config = config or {}

    def _setting(self, key, env_name, default=""):
        explicit = self.config.get(key, "")
        if explicit:
            return str(explicit)
        return os.environ.get(str(self.config.get(f"{key}_env", env_name)), default)

    def _access_token(self):
        token = self._setting("access_token", "REDDIT_ACCESS_TOKEN")
        if token:
            return token
        client_id = self._setting("client_id", "REDDIT_CLIENT_ID")
        client_secret = self._setting("client_secret", "REDDIT_CLIENT_SECRET")
        refresh_token = self._setting("refresh_token", "REDDIT_REFRESH_TOKEN")
        if not (client_id and client_secret and refresh_token):
            return ""
        data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        credentials = (f"{client_id}:{client_secret}").encode()
        import base64

        request = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=data,
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.config.get("user_agent", "ai-self-media-tools/1.0.0 by configured-operator"),
            },
        )
        with urllib.request.urlopen(request, timeout=int(self.config.get("timeout", 20))) as response:
            payload = json.loads(response.read())
        return payload.get("access_token", "")

    def _request_listing(self, subreddit, token):
        params = {
            "limit": int(self.config.get("limit_per_subreddit", 25)),
            "raw_json": 1,
        }
        query = str(self.config.get("query", "")).strip()
        if query:
            path = f"/r/{subreddit}/search"
            params.update({"q": query, "restrict_sr": "on", "sort": self.config.get("sort", "hot"), "t": self.config.get("time_filter", "week")})
        else:
            path = f"/r/{subreddit}/{self.config.get('sort', 'hot')}"
        url = self.API_ROOT + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": self.config.get("user_agent", "ai-self-media-tools/1.0.0 by configured-operator"),
            },
        )
        with urllib.request.urlopen(request, timeout=int(self.config.get("timeout", 20))) as response:
            return json.loads(response.read())

    def collect(self):
        if not self.config.get("enabled", False):
            return []
        token = self._access_token()
        if not token:
            return []
        subreddits = [str(item).strip().strip("/").removeprefix("r/") for item in self.config.get("subreddits", []) if str(item).strip()]
        keywords = [str(item) for item in self.config.get("keywords", []) if str(item).strip()]
        items = []
        for subreddit in subreddits:
            payload = self._request_listing(subreddit, token)
            for child in payload.get("data", {}).get("children", []):
                data = child.get("data", {})
                title = str(data.get("title", "")).strip()
                if not title:
                    continue
                score = max(0, int(data.get("score", 0) or 0))
                comments = max(0, int(data.get("num_comments", 0) or 0))
                ratio = float(data.get("upvote_ratio", 0) or 0)
                permalink = str(data.get("permalink", ""))
                url = permalink if permalink.startswith("http") else "https://www.reddit.com" + permalink
                items.append(
                    {
                        "title": title,
                        "source": "reddit:" + str(data.get("subreddit") or subreddit),
                        "url": url,
                        "points": round(score + comments * 1.5 + ratio * 20, 3),
                        "score": score,
                        "comments": comments,
                        "upvote_ratio": ratio,
                        "created_utc": data.get("created_utc", 0),
                        "subreddit": str(data.get("subreddit") or subreddit),
                        "keywords": keywords,
                    }
                )
        return items
