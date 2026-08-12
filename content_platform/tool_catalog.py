"""Canonical decisions for external content-production capabilities.

This keeps evaluation separate from execution: existing project adapters are
the runtime, while external projects contribute only documented patterns.
"""

from __future__ import annotations

from typing import Any


TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "video_shotcraft": {
        "source": "video-shotcraft",
        "decision": "extract_patterns",
        "runtime": "scripts/shotcraft_moves.py",
        "contribution": "shot recipes, timing, and visual acceptance checks",
        "route": "video.motion_effects",
    },
    "openmontage": {
        "source": "OpenMontage",
        "decision": "already_covered",
        "runtime": "scripts/video_toolchain_runner.py",
        "contribution": "manifest-driven staged rendering and reuse",
        "route": "video.workflow_manifest",
    },
    "krillinai": {
        "source": "KrillinAI",
        "decision": "extract_patterns",
        "runtime": "scripts/render_checkpoint.py + video_toolchain_runner.py",
        "contribution": "stage artifacts, resume, and localization evidence",
        "route": "video.localization",
    },
    "gzh_design": {
        "source": "gzh-design-skill",
        "decision": "already_covered",
        "runtime": "content_platform/gzh_design.py",
        "contribution": "theme selection and WeChat layout rendering",
        "route": "article.wechat_layout",
    },
    "baoyu_guizang_humanizer": {
        "source": "baoyu/guizang/Humanizer-zh",
        "decision": "already_covered",
        "runtime": "Hermes skills bridge + project formatters",
        "contribution": "copy, cover, illustration, and humanization patterns",
        "route": "article.content_quality",
    },
    "account_teardown": {
        "source": "account/viral teardown method",
        "decision": "implement_project_adapter",
        "runtime": "content_platform/viral_monitor.py + performance collectors",
        "contribution": "account-level winners, hooks, comments, and follow conversion",
        "route": "operations.account_analysis",
    },
    "vox_broll": {
        "source": "Vox/B-roll collage workflow",
        "decision": "defer_until_route_is_needed",
        "runtime": "video_toolchain selected pipeline",
        "contribution": "alternate visual form for opinion and story content",
        "route": "video.form_router",
    },
    "moneyprinterturbo": {
        "source": "MoneyPrinterTurbo",
        "decision": "do_not_integrate",
        "runtime": "none",
        "contribution": "covered by existing guarded video pipeline",
        "route": "none",
    },
    "media_crawler": {
        "source": "MediaCrawler",
        "decision": "do_not_integrate",
        "runtime": "none",
        "contribution": "use approved source matrix and Agent-Reach fallbacks",
        "route": "none",
    },
}


def catalog_snapshot() -> dict[str, Any]:
    """Return a serializable catalog for plans and audit reports."""
    counts: dict[str, int] = {}
    for item in TOOL_CATALOG.values():
        decision = str(item["decision"])
        counts[decision] = counts.get(decision, 0) + 1
    return {
        "version": "tool_catalog_v1",
        "tools": TOOL_CATALOG,
        "decision_counts": counts,
    }

