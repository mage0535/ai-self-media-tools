import json
import math
import os
import re
import subprocess
import urllib.parse
import urllib.request
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
        reddit_items = []
        reddit_cfg = self.config.get("reddit", {})
        if reddit_cfg.get("enabled"):
            reddit_items = RedditTrendCollector(reddit_cfg).collect()
        data_dir = Path(self.config.get("legacy_data_dir", str(trend_cache_dir())))
        if refresh:
            script = Path(self.config.get("legacy_script", str(project_home() / "external" / "scripts" / "trend_collector.py")))
            if script.is_file():
                proc = subprocess.run(["python3", str(script)], capture_output=True, text=True, timeout=120, check=False)
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout)[-500:])
        files = sorted(data_dir.glob("trending_*.json"), reverse=True)
        if not files:
            return reddit_items
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("trends", payload.get("items", []))
        seen, result = set(), []
        for row in rows:
            if isinstance(row, str):
                row = {"title": row}
            title = str(row.get("title", "")).strip()
            key = title.casefold()
            if title and key not in seen:
                seen.add(key)
                result.append({"title": title, "source": row.get("source", "unknown"), "url": row.get("url", "")})
        for item in reddit_items:
            title = str(item.get("title", "")).strip()
            key = title.casefold()
            if title and key not in seen:
                seen.add(key)
                result.append(item)
        return result


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
                "User-Agent": self.config.get("user_agent", "ai-self-media-tools/0.2 by configured-operator"),
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
                "User-Agent": self.config.get("user_agent", "ai-self-media-tools/0.2 by configured-operator"),
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
