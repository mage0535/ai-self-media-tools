"""Load official public activity/ranking signals as bounded strategy context.

These signals are reference evidence only. They never become a native hotspot
identity and never bypass lane, claim, dedupe, or quality gates.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

READY_STATUSES = {"verified", "verified_via_shared_douyin_source", "backend_loaded"}
OFFICIAL_EVIDENCE_TYPES = {"official_activity", "official_keyword", "official_reference"}
SIGNAL_TYPE_TO_EVIDENCE = {
    "official_feed_and_campaign": "official_activity",
    "official_creator_activity": "official_activity",
    "creator_backend_activity": "official_activity",
    "hot_list": "official_keyword",
    "official_rank": "official_keyword",
    "creator_metrics_and_search_queries": "official_keyword",
    "official_explore": "official_keyword",
    "official_trending_and_studio": "official_keyword",
    "creator_backend_and_hot_questions": "official_keyword",
}
_NOISE_WORDS = {
    "登录", "首页", "关注", "朋友", "我的", "消息", "通知", "投稿", "搜索",
    "精选", "推荐", "读屏", "客户端", "创作中心", "数据中心", "活动中心",
    "支持常用格式", "加载失败", "登录后", "过去 7 天", "近 7 日", "近 30 日",
    "抖音热榜", "排行榜", "所有人", "小游戏", "充钻石", "热点视频",
    "读屏标签已关闭", "开启读屏标签",
}


def _is_topic_text(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 180:
        return False
    if text.isdigit() or text.replace(".", "", 1).isdigit():
        return False
    if text in _NOISE_WORDS or any(text.startswith(word) for word in _NOISE_WORDS if word not in {"推荐", "关注"}):
        return False
    if "参与" in text or "万人参与" in text or "万热度" in text or text.endswith("热度"):
        return False
    if text.startswith(("@", "00:", "01:")):
        return False
    return True


def _candidate_paths(data_dir: str | Path | None = None) -> list[Path]:
    explicit = str(os.environ.get("OFFICIAL_PLATFORM_SIGNAL_MATRIX") or "").strip()
    paths = [Path(explicit)] if explicit else []
    root = Path(data_dir or os.environ.get("AI_SELF_MEDIA_DATA_DIR") or Path.cwd())
    paths.extend([
        root / "overnight" / datetime.now(timezone.utc).date().isoformat() / "official-platform-signal-matrix-v3.json",
        root / "overnight" / "official-platform-signal-matrix-v3.json",
    ])
    paths.extend(sorted((root / "overnight").glob("*/official-platform-signal-matrix-v3.json"), reverse=True))
    return list(dict.fromkeys(paths))


def load_official_reference_signals(platform: str, *, data_dir: str | Path | None = None) -> dict[str, Any]:
    normalized = str(platform or "").casefold()
    for path in _candidate_paths(data_dir):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = [row for row in (payload.get("platforms") or [])
                if isinstance(row, dict) and str(row.get("platform") or "").casefold() == normalized]
        if not rows:
            continue
        row = rows[0]
        status = str(row.get("status") or "").casefold()
        if not _fresh_capture(row.get("captured_at"), datetime.now(timezone.utc), max_age_hours=48):
            continue
        raw_signal_type = str(row.get("signal_type") or "official_reference").casefold()
        evidence_type = str(row.get("evidence_type") or SIGNAL_TYPE_TO_EVIDENCE.get(raw_signal_type) or raw_signal_type).casefold()
        if evidence_type not in OFFICIAL_EVIDENCE_TYPES:
            evidence_type = "official_reference"
        raw_signals = [str(item).strip() for item in (row.get("reference_topics") or row.get("signals") or [])]
        if raw_signal_type == "creator_metrics":
            raw_signals = []
        elif raw_signal_type == "creator_metrics_and_search_queries":
            raw_signals = [
                item for item in raw_signals
                if not any(token in item for token in ("观看次数", "主页访问量", "赞", "评论", "分享", "过去 7 天", "预估奖励", "流量来源"))
            ]
        return {
            "status": "ready" if status in READY_STATUSES else "insufficient",
            "source_status": status,
            "signal_type": raw_signal_type,
            "evidence_type": evidence_type,
            "official_url": str(row.get("official_url") or ""),
            "final_url": str(row.get("final_url") or row.get("official_url") or ""),
            "captured_at": str(row.get("captured_at") or ""),
            "native_verified": False,
            "validity": _validity(row, datetime.now(timezone.utc)),
            "expires_at": str(row.get("expires_at") or row.get("valid_until") or ""),
            "signals": [item for item in raw_signals if _is_topic_text(item)][:80],
            "evidence_sha256": str(row.get("evidence_sha256") or ""),
            "reason": str(row.get("reason") or ""),
            "matrix_path": str(path),
        }
    return {"status": "insufficient", "source_status": "missing", "signal_type": "official_reference", "evidence_type": "official_reference", "signals": [], "reason": "official platform signal matrix not found"}


def build_reference_items(platform: str, *, data_dir: str | Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = load_official_reference_signals(platform, data_dir=data_dir)
    if evidence.get("status") != "ready":
        return evidence, []
    source = f"{str(platform).casefold()}:official_reference"
    items = []
    for index, title in enumerate(evidence.get("signals") or []):
        if len(title) < 2:
            continue
        signal = {
            "signal_type": evidence.get("signal_type"),
            "evidence_type": evidence.get("evidence_type", evidence.get("signal_type")),
            "official_url": evidence.get("official_url"),
            "captured_at": evidence.get("captured_at"),
            "native_verified": False,
            "native_evidence": False,
            "validity": evidence.get("validity", "unknown"),
            "expires_at": evidence.get("expires_at", ""),
            "evidence_sha256": evidence.get("evidence_sha256"),
            "source_status": evidence.get("source_status"),
        }
        item = {
            "title": title[:180], "source": source, "url": evidence.get("official_url") or "",
            "points": max(1, 80 - index), "score": round(max(0.35, 0.78 - index * 0.01), 3),
            "platform": str(platform).casefold(), "official_reference_only": True,
            "native_verified": False, "native_evidence": False,
            "evidence_type": evidence.get("evidence_type", evidence.get("signal_type")),
            "validity": evidence.get("validity", "unknown"), "expires_at": evidence.get("expires_at", ""),
            "official_reference_signal": signal,
        }
        item["reference_evidence_sha256"] = hashlib.sha256(json.dumps(signal, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        items.append(item)
    return evidence, items


def build_selection_items(
    platform: str,
    lane_keywords: list[str] | tuple[str, ...],
    *,
    data_dir: str | Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compile verified first-party activity/keyword rows into candidates.

    Reference-only rows remain separate. This adapter requires lane overlap and
    complete provenance before a signal may enter selection.
    """
    evidence = load_official_reference_signals(platform, data_dir=data_dir)
    evidence_type = str(evidence.get("evidence_type") or "")
    if evidence.get("status") != "ready" or evidence_type not in {"official_activity", "official_keyword"}:
        return evidence, []
    if evidence.get("validity") in {"expired", "invalid"}:
        return evidence, []
    official_url = str(evidence.get("official_url") or "")
    captured_at = str(evidence.get("captured_at") or "")
    evidence_hash = str(evidence.get("evidence_sha256") or "")
    if not official_url.startswith(("https://", "http://")) or not captured_at or len(evidence_hash) != 64:
        return evidence, []
    from .associated_hotspot import hotspot_mode_for_platform

    words = [str(word).casefold().strip() for word in lane_keywords if str(word).strip()]
    items = []
    for index, title in enumerate(evidence.get("signals") or []):
        text = str(title).strip()
        if not _is_topic_text(text):
            continue
        matched = [word for word in words if word in text.casefold()]
        if words and not matched:
            continue
        lane_score = min(1.0, max(0.55, len(matched) / max(1, min(4, len(words)))))
        items.append({
            "platform": str(platform).casefold(),
            "title": text[:180],
            "source": f"{str(platform).casefold()}:official_signal",
            "url": official_url,
            "points": max(1, 100 - index),
            "rank": index + 1,
            "evidence_type": evidence_type,
            "official_reference_only": False,
            "native_verified": False,
            "captured_at": captured_at,
            "expires_at": evidence.get("expires_at", ""),
            "lane_fit_score": lane_score,
            "semantic_fit_score": lane_score,
            "content_value_score": 0.7,
            "actionability_score": 0.65,
            "saturation_score": 0.25,
            "association_mode": hotspot_mode_for_platform(platform),
            "evidence_hash": evidence_hash,
            "collector": "official_platform_signal_matrix",
            "observed_rank": index + 1,
        })
    return evidence, items


def _validity(row: dict[str, Any], now: datetime) -> str:
    raw = str(row.get("expires_at") or row.get("valid_until") or "").strip()
    if not raw:
        return "unknown"
    try:
        expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return "valid" if expiry > now else "expired"
    except ValueError:
        return "invalid"


def _fresh_capture(value: Any, now: datetime, *, max_age_hours: float) -> bool:
    try:
        captured = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    age = (now - captured.astimezone(timezone.utc)).total_seconds() / 3600
    return -1 <= age <= float(max_age_hours)
