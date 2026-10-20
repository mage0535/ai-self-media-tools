"""Distilled per-account compact loader — first-load priority for ai-self-media-tools."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

def load_distilled_per_account_compact(platform: str, *, path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path else ROOT / "data" / "intel" / "distilled_per_account_latest.json"
    if not source.is_file():
        return {"version": "distilled_per_account_compact_v1", "status": "missing"}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"version": "distilled_per_account_compact_v1", "status": "invalid", "error": str(exc)[:160]}
    platform = str(platform or "").casefold().strip()
    accounts = payload.get("accounts") or {}
    data = accounts.get(platform)
    # douyin_ai / douyin_pet have separate entries; douyin maps to douyin_ai
    if data is None and platform in {"douyin", "douyin_ai"}:
        data = accounts.get("douyin_ai") or accounts.get("douyin")
    if not isinstance(data, dict):
        return {"version": "distilled_per_account_compact_v1", "status": "missing_platform"}
    return {
        "version": "distilled_per_account_compact_v1",
        "status": "ready" if data.get("ready") else "insufficient",
        "label": data.get("label", ""),
        "strong": data.get("strong", 0),
        "total": data.get("total", 0),
        "evidence_status": data.get("evidence_status", ""),
        "title_formula": data.get("title_formula", ""),
        "cat_role": data.get("cat_role", ""),
        "publish_mode": data.get("publish_mode", ""),
        "content_form": data.get("content_form", ""),
        "recommended_patterns": data.get("recommended_patterns") or [],
        "generation_requirements": data.get("generation_requirements") or [],
        "top3": data.get("top3") or [],
        "dedup_rule": data.get("dedup_rule", ""),
        "universal": payload.get("universal") or {},
    }
