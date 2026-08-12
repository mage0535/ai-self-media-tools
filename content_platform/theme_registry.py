"""Verified theme routing for formats that have a concrete renderer."""

from __future__ import annotations


THEME_REGISTRY_VERSION = "theme_registry_v1"

# IDs are stable and intentionally limited to themes with an installed renderer.
THEMES = (
    {"id": "wechat_practical", "platforms": {"wechat"}, "forms": {"article", "guide", "checklist"}, "signals": {"workflow", "tutorial", "checklist", "步骤"}, "gzh_index": 0},
    {"id": "wechat_contrast", "platforms": {"wechat"}, "forms": {"article", "case", "comparison"}, "signals": {"compare", "versus", "case", "对比", "复盘"}, "gzh_index": 1},
    {"id": "wechat_minimal", "platforms": {"wechat"}, "forms": {"article", "report", "analysis"}, "signals": {"report", "analysis", "research", "报告", "分析"}, "gzh_index": 2},
    {"id": "wechat_editorial", "platforms": {"wechat"}, "forms": {"article", "story", "opinion"}, "signals": {"story", "reflection", "经验", "故事"}, "gzh_index": 3},
)


def select_theme(platform: str, topic: str, content_form: str = "article", recent_theme_ids=None) -> dict:
    platform = str(platform or "").casefold()
    content_form = str(content_form or "article").casefold()
    words = str(topic or "").casefold()
    recent = {str(item) for item in (recent_theme_ids or [])}
    candidates = [row for row in THEMES if platform in row["platforms"] and (content_form in row["forms"] or "article" in row["forms"])]
    if not candidates:
        return {"selected": "", "reason": "no verified renderer theme for platform", "candidates": []}
    ranked = sorted(candidates, key=lambda row: (sum(signal.casefold() in words for signal in row["signals"]), row["id"] not in recent), reverse=True)
    selected = ranked[0]
    return {"selected": selected["id"], "reason": "topic/form signal match" if any(signal.casefold() in words for signal in selected["signals"]) else "verified platform default", "gzh_index": selected["gzh_index"], "candidates": [row["id"] for row in candidates], "version": THEME_REGISTRY_VERSION}


def resolve_wechat_theme(selection: dict) -> str:
    """Translate a stable ID to the installed gzh-design theme label."""
    from .gzh_design import VALID_THEMES

    index = int((selection or {}).get("gzh_index", 0))
    return VALID_THEMES[index] if 0 <= index < len(VALID_THEMES) else VALID_THEMES[0]
