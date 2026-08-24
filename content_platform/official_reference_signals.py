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
    return paths


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
        signal_type = str(row.get("signal_type") or "official_reference")
        raw_signals = [str(item).strip() for item in (row.get("reference_topics") or row.get("signals") or [])]
        if signal_type == "creator_metrics":
            raw_signals = []
        elif signal_type == "creator_metrics_and_search_queries":
            raw_signals = [
                item for item in raw_signals
                if not any(token in item for token in ("观看次数", "主页访问量", "赞", "评论", "分享", "过去 7 天", "预估奖励", "流量来源"))
            ]
        return {
            "status": "ready" if status in READY_STATUSES else "insufficient",
            "source_status": status,
            "signal_type": signal_type,
            "official_url": str(row.get("official_url") or ""),
            "final_url": str(row.get("final_url") or row.get("official_url") or ""),
            "captured_at": str(row.get("captured_at") or ""),
            "native_verified": row.get("native_verified") is True,
            "signals": [item for item in raw_signals if _is_topic_text(item)][:80],
            "evidence_sha256": str(row.get("evidence_sha256") or ""),
            "reason": str(row.get("reason") or ""),
            "matrix_path": str(path),
        }
    return {"status": "insufficient", "source_status": "missing", "signal_type": "official_reference", "signals": [], "reason": "official platform signal matrix not found"}


def build_reference_items(platform: str, *, data_dir: str | Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = load_official_reference_signals(platform, data_dir=data_dir)
    if str(platform or "").casefold() == "douyin_pet" and not evidence.get("signals"):
        evidence = load_official_reference_signals("douyin_ai", data_dir=data_dir)
        if evidence.get("status") == "ready":
            evidence["shared_base_platform"] = "douyin_ai"
    if evidence.get("status") != "ready":
        return evidence, []
    source = f"{str(platform).casefold()}:official_reference"
    items = []
    for index, title in enumerate(evidence.get("signals") or []):
        if len(title) < 2:
            continue
        signal = {
            "signal_type": evidence.get("signal_type"),
            "official_url": evidence.get("official_url"),
            "captured_at": evidence.get("captured_at"),
            "native_verified": evidence.get("native_verified"),
            "evidence_sha256": evidence.get("evidence_sha256"),
            "source_status": evidence.get("source_status"),
        }
        item = {
            "title": title[:180], "source": source, "url": evidence.get("official_url") or "",
            "points": max(1, 80 - index), "score": round(max(0.35, 0.78 - index * 0.01), 3),
            "platform": str(platform).casefold(), "official_reference_only": True,
            "official_reference_signal": signal,
        }
        item["reference_evidence_sha256"] = hashlib.sha256(json.dumps(signal, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        items.append(item)
    return evidence, items
