import json
import math
import re
import subprocess
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
        data_dir = Path(self.config.get("legacy_data_dir", str(trend_cache_dir())))
        if refresh:
            script = Path(self.config.get("legacy_script", str(project_home() / "external" / "scripts" / "trend_collector.py")))
            if script.is_file():
                proc = subprocess.run(["python3", str(script)], capture_output=True, text=True, timeout=120, check=False)
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout)[-500:])
        files = sorted(data_dir.glob("trending_*.json"), reverse=True)
        if not files:
            return []
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
        return result
