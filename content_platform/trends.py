import json
import math
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .paths import agent_home, project_home, trend_cache_dir
from .source_quality import source_is_rankable
from .associated_hotspot import score_topic_with_hotspot


def normalize_topic(title):
    return " ".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(title).casefold()))


NATIVE_SEARCH_DOMAINS = {
    "wechat": ("mp.weixin.qq.com", "weixin.qq.com"),
    "kuaishou": ("kuaishou.com", "gifshow.com"),
    "juejin": ("juejin.cn",),
    "shipinhao": ("channels.weixin.qq.com", "weixin.qq.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "twitter": ("x.com", "twitter.com"),
}


def _has_native_result(source: str, items: list[dict]) -> bool:
    domains = NATIVE_SEARCH_DOMAINS.get(str(source or "").casefold(), ())
    if not domains:
        return True
    for item in items:
        host = urllib.parse.urlparse(str(item.get("url") or "")).hostname or ""
        host = host.casefold()
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return True
    return False


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
        # Fallback hypotheses document a failed source; they are not evidence
        # and must never be promoted into an automatic topic candidate.
        if not source_is_rankable(item):
            continue
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
        hotspot_bonus = 0.0
        hotspot_gate = None
        if item.get("associated_hotspot"):
            hotspot_result = score_topic_with_hotspot(
                {
                    "platform_fit": min(1.0, fit_score / 3.0),
                    "utility": 0.8 if any(token in title.casefold() for token in ("workflow", "教程", "方法", "步骤")) else 0.5,
                    "novelty": 0.7,
                },
                item.get("associated_hotspot"),
            )
            hotspot_gate = hotspot_result["hotspot_gate"]
            if not hotspot_gate.get("passed"):
                continue
            hotspot_bonus = float(hotspot_result.get("hotspot_bonus") or 0.0)
            score += hotspot_bonus * 4.0
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
            "hotspot_bonus": round(hotspot_bonus, 3),
            "hotspot_gate": hotspot_gate or {"passed": False, "failures": ["hotspot_not_selected"]},
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
                elif source_items and not _has_native_result(source_name, source_items):
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
            "wechat": {"enabled": False, "limit": 20, "timeout": 8, "query": "\u516c\u4f17\u53f7 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387"},
            "wewrite_hotspots": {"enabled": False, "limit": 20, "timeout": 8},
            "kuaishou": {"enabled": False, "limit": 20, "timeout": 8, "query": "\u5feb\u624b \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387 \u77ed\u89c6\u9891"},
            "juejin": {"enabled": False, "limit": 20, "timeout": 8, "query": "AI \u5de5\u5177 \u6548\u7387 \u5de5\u4f5c\u6d41 site:juejin.cn"},
            "shipinhao": {"enabled": False, "limit": 20, "timeout": 8, "query": "\u89c6\u9891\u53f7 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387"},
            "xiaohongshu": {"enabled": False, "limit": 20, "timeout": 8, "query": "\u5c0f\u7ea2\u4e66 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387 site:xiaohongshu.com"},
            "youtube": {"enabled": False, "limit": 20, "timeout": 8, "query": "AI workflow automation productivity site:youtube.com"},
            "tiktok": {"enabled": False, "limit": 20, "timeout": 8, "query": "AI workflow automation productivity site:tiktok.com"},
            # Optional local adapter. It is never treated as a publisher and is
            # disabled until an operator explicitly configures the command.
            "agent_reach": {"enabled": False, "limit": 20, "timeout": 20},
        }
        if isinstance(configured, dict):
            for name, value in configured.items():
                if isinstance(value, dict):
                    defaults[name] = {**defaults.get(name, {}), **value}
                else:
                    defaults[name] = {"enabled": bool(value)}
        # Inject the shared SearXNG endpoint into every web-search source so a
        # single config key revives all search-backed collectors.
        searxng_url = str(self.config.get("searxng_url") or os.environ.get("SEARXNG_URL") or os.environ.get("SEARXNG_BASE_URL") or "").rstrip("/")
        if searxng_url:
            for cfg in defaults.values():
                if isinstance(cfg, dict):
                    cfg["searxng_url"] = searxng_url
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
        if self.name in ("twitter", "x"):
            return self._web_search_source("twitter", "AI tools workflow automation developer productivity")
        platform_queries = {
            "wechat": "\u516c\u4f17\u53f7 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387",
            "kuaishou": "\u5feb\u624b \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387 \u77ed\u89c6\u9891",
            "juejin": "AI \u5de5\u5177 \u6548\u7387 \u5de5\u4f5c\u6d41 site:juejin.cn",
            "shipinhao": "\u89c6\u9891\u53f7 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387",
            "xiaohongshu": "\u5c0f\u7ea2\u4e66 \u70ed\u95e8 AI \u5de5\u5177 \u6548\u7387 site:xiaohongshu.com",
            "youtube": "AI workflow automation productivity site:youtube.com",
            "tiktok": "AI workflow automation productivity site:tiktok.com",
        }
        if self.name in platform_queries:
            return self._web_search_source(self.name, self._native_query(platform_queries[self.name]))
        if self.name == "bilibili":
            return self._bilibili()
        if self.name == "zhihu":
            try:
                return self._zhihu_cli_hot()
            except Exception as exc:
                if not self.config.get("source_fallback_enabled", True):
                    raise
                fallback = self._web_search_source("zhihu", "AI 工具 效率 工作流 site:zhihu.com")
                if fallback:
                    return fallback
                raise
        if self.name == "douyin":
            return self._douyin_hot_board()
        if self.name == "wewrite_hotspots":
            return self._wewrite_hotspots()
        if self.name == "agent_reach":
            return self._agent_reach()
        raise ValueError(f"unknown direct trend source: {self.name}")

    def _native_query(self, query: str) -> str:
        """Constrain web-search transport to the target platform domain."""
        if "site:" in query.casefold():
            return query
        domains = {
            "wechat": "mp.weixin.qq.com",
            "kuaishou": "kuaishou.com",
            "juejin": "juejin.cn",
            "shipinhao": "channels.weixin.qq.com",
            "xiaohongshu": "xiaohongshu.com",
            "youtube": "youtube.com",
            "tiktok": "tiktok.com",
            "twitter": "x.com",
        }
        domain = domains.get(self.name)
        return f"{query} site:{domain}" if domain else query

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
            upstream_source = str(row.get("source") or "").strip()
            items.append({
                **row,
                "title": title,
                "source": "wewrite_hotspots" if not upstream_source or upstream_source == "wewrite_hotspots" else f"wewrite_hotspots:{upstream_source}",
                **({"upstream_source": upstream_source} if upstream_source else {}),
                "url": row.get("url", ""),
                "points": int(row.get("points") or row.get("score") or row.get("heat") or 0),
            })
        return items

    def _agent_reach(self):
        """Read Agent-Reach trend output through an explicit local command.

        Agent-Reach is a collection fallback only. A missing binary or invalid
        output fails the source and remains visible in the trend report.
        """
        command = self.config.get("command") or self.config.get("agent_reach_command")
        if isinstance(command, str):
            command = shlex.split(command)
        if not isinstance(command, list) or not command:
            raise RuntimeError("agent_reach command is not configured")
        proc = subprocess.run(
            [str(part) for part in command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "agent_reach command failed")[:240])
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"agent_reach returned invalid JSON: {exc.msg}") from exc
        rows = payload if isinstance(payload, list) else payload.get("items", payload.get("results", []))
        items = []
        for row in rows[: self.limit]:
            if isinstance(row, str):
                row = {"title": row}
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("topic") or row.get("name") or "").strip()
            if not title:
                continue
            items.append({
                **row,
                "title": title,
                "source": str(row.get("source") or "agent_reach"),
                "url": str(row.get("url") or ""),
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
        try:
            payload = self._request_json(f"https://api.github.com/search/repositories?{q}")
        except Exception:
            payload = {}
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
        if items:
            return items
        # API 限流/失败时回退到本地 github_trending 缓存（防抖）
        return self._github_local_cache()

    def _github_local_cache(self):
        """Fallback: read the locally cached GitHub trending snapshot (Hermes)."""
        candidates = [
            Path(os.environ.get("HERMES_DATA_DIR", str(agent_home() / "data"))) / "github_trending.json",
            agent_home() / "data" / "github_trending.json",
        ]
        items = []
        for path in candidates:
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows = payload.get("ranked") if isinstance(payload.get("ranked"), list) else None
            if rows is None and isinstance(payload.get("projects"), dict):
                rows = list(payload["projects"].values())[: self.limit]
            projects_map = payload.get("projects") if isinstance(payload.get("projects"), dict) else {}
            for row in (rows or [])[: self.limit]:
                if isinstance(row, str):
                    repo = row.strip()
                    detail = projects_map.get(repo, {}) if isinstance(detail := projects_map.get(repo), dict) else {}
                    title = str(detail.get("title") or repo or "").strip()
                    if not title:
                        continue
                    items.append({
                        "title": title,
                        "source": "github",
                        "url": detail.get("url") or detail.get("html_url") or f"https://github.com/{repo}",
                        "points": int(detail.get("stars") or detail.get("stargazers_count") or detail.get("points") or 0),
                        "language": detail.get("language", ""),
                    })
                    continue
                title = str(row.get("title") or row.get("name") or row.get("full_name") or "").strip()
                if not title:
                    continue
                items.append({
                    "title": title,
                    "source": "github",
                    "url": row.get("url") or row.get("html_url") or f"https://github.com/{row.get('full_name') or row.get('name')}",
                    "points": int(row.get("stars") or row.get("stargazers_count") or row.get("points") or 0),
                    "language": row.get("language", ""),
                })
            if items:
                break
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

    def _zhihu_cli_hot(self):
        """Zhihu hot list via official open-platform CLI first, then cookie CLI."""
        try:
            from .zhihu_open_adapter import ZhihuOpenAdapter

            adapter = ZhihuOpenAdapter(timeout=int(self.config.get("timeout", 15)) + 30)
            items = adapter.trending(limit=self.limit, retries=1, retry_delay=10)
            if items:
                return items
        except Exception:
            pass
        from .zhihu_cli_adapter import ZhihuCliAdapter
        adapter = ZhihuCliAdapter(timeout=int(self.config.get("timeout", 15)) + 30)
        return adapter.fetch_hot(limit=self.limit)

    def _douyin_hot_board(self):
        """Collect the native Douyin hot board with observed heat values."""
        payload = self._request_json(
            "https://www.douyin.com/aweme/v1/hot/search/list/",
            headers={"Referer": "https://www.douyin.com/"},
        )
        rows = (payload.get("data") or {}).get("word_list") or []
        items = []
        for row in rows[: self.limit]:
            title = str(row.get("word") or "").strip()
            if not title:
                continue
            items.append({
                "title": title,
                "source": "douyin",
                "url": row.get("url") or "https://www.douyin.com/search/" + urllib.parse.quote(title),
                "points": int(row.get("hot_value") or 0),
                "rank": int(row.get("position") or 0),
                "label": row.get("label"),
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
                "provenance_kind": "synthetic_fallback",
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
