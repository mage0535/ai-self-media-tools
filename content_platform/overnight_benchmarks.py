"""Attach a same-lane breakdown (viral_breakdown) to ready overnight tasks.

Generation requires a breakdown observed within 24 h on the task's own
platform.  Only platforms with a typed public full-text collector get one;
other ready rows are blocked with the reason instead of failing later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _juejin(items: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    from .juejin_native_article import collect_samples

    hot = [item for item in items if item.get("source") == "juejin"]
    return collect_samples(hot, out_dir / "juejin")


def _videos(name: str, feed):
    def collect(items: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
        from . import video_sample_collector as videos

        return videos.collect_samples(feed(videos), out_dir / name)
    return collect


COLLECTORS = {
    "juejin": _juejin,
    "bilibili_ai": _videos("bilibili_ai", lambda videos: videos.bilibili_candidates("ai")),
    "bilibili_pet": _videos("bilibili_pet", lambda videos: videos.bilibili_candidates("pet")),
    "tiktok_ai": _videos("tiktok_ai", lambda videos: videos.tiktok_candidates()),
    "youtube_ai": _videos("youtube_ai", lambda videos: videos.youtube_candidates()),
}
# Owner 10-28: lanes without their own typed collector use another platform's real public samples.
# lane -> (collector, platform the samples were observed on); the breakdown keeps that platform
# and is marked cross_platform_source.
LANE_COLLECTORS = {
    "juejin": ("juejin", "juejin"), "zhihu": ("juejin", "juejin"), "wechat": ("juejin", "juejin"),
    # Xiaohongshu is never read automatically (owner rule); its carousel takes the article reference.
    "xiaohongshu": ("juejin", "juejin"),
    **{lane: ("bilibili_ai", "bilibili") for lane in ("bilibili", "douyin", "douyin_ai", "kuaishou", "shipinhao")},
    "douyin_pet": ("bilibili_pet", "bilibili"),
    "tiktok": ("tiktok_ai", "tiktok"),
    "youtube": ("youtube_ai", "youtube"),
}


def attach_breakdowns(prepared: dict[str, Any], items: list[dict[str, Any]], out_dir: str | Path) -> dict[str, Any]:
    from .task_source_inputs import _observed_strategy_inputs

    cache: dict[str, Any] = {}
    rows_by_collector: dict[str, Any] = {}
    for task in prepared.get("tasks") or []:
        platform = str(task.get("platform") or "")
        if task.get("state") != "ready_for_plan":
            continue
        if platform not in cache:
            name, source_platform = LANE_COLLECTORS.get(platform, (platform, platform))
            try:
                if name not in COLLECTORS:
                    raise ValueError("no typed public same-lane collector for this platform")
                if name not in rows_by_collector:  # Lanes sharing a collector observe once.
                    rows_by_collector[name] = COLLECTORS[name](items, Path(out_dir))
                cache[platform] = _observed_strategy_inputs(source_platform, {"items": rows_by_collector[name]})
                if source_platform != platform:
                    cache[platform]["cross_platform_source"] = source_platform
            except Exception as exc:  # One platform's benchmark must not abort the batch.
                cache[platform] = {"error": f"same-lane breakdown unavailable: {str(exc)[:200]}"}
        strategy = cache[platform]
        if "error" in strategy:
            task.update(state="blocked", reason=strategy["error"])
        else:
            task.setdefault("brief", {}).update(strategy)
    return prepared
