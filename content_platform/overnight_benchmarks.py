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


def _zhihu_mediacrawler(items: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    from . import mediacrawler_collector as mc

    return mc.zhihu_samples(mc.search("zhihu", out_dir / "zhihu_mc"))


def _videos(name: str, feed):
    def collect(items: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
        from . import video_sample_collector as videos

        return videos.collect_samples(feed(videos), out_dir / name)
    return collect


COLLECTORS = {
    "juejin": _juejin,
    "zhihu_mc": _zhihu_mediacrawler,
    "bilibili_ai": _videos("bilibili_ai", lambda videos: videos.bilibili_candidates("ai")),
    "bilibili_pet": _videos("bilibili_pet", lambda videos: videos.bilibili_candidates("pet")),
    "tiktok_ai": _videos("tiktok_ai", lambda videos: videos.tiktok_candidates()),
    "tiktok_pet": _videos("tiktok_pet", lambda videos: videos.tiktok_candidates(pet=True)),
    "youtube_ai": _videos("youtube_ai", lambda videos: videos.youtube_candidates()),
    "youtube_pet": _videos("youtube_pet", lambda videos: videos.youtube_candidates(pet=True)),
    "youtube_ai_scenario": _videos("youtube_ai_scenario", lambda videos: videos.youtube_candidates(scenario=True)),
}
# Owner 11-02: a lane's own platform data (MediaCrawler) comes first; LANE_COLLECTORS is the labelled fallback.
NATIVE_COLLECTORS = {"zhihu": ("zhihu_mc", "zhihu")}
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
# 11-03: Bilibili answered -352 (risk control; never worked around), which blocked douyin_pet outright.
# Further same-genre sources are tried in order before a lane is blocked.
FALLBACK_COLLECTORS = {"douyin_pet": (("youtube_pet", "youtube"), ("tiktok_pet", "tiktok"))}


# Owner 10-31: other platforms' pet videos are analysed for learning only; our videos are original.
# Lanes whose video plan needs cross-platform reference works from >= 2 sources.
# Kuaishou counts only adjacent short-video platforms; its AI references are real-world scenarios (owner 10-30).
REFERENCE_COLLECTORS = {"douyin_pet": ("bilibili_pet", "youtube_pet", "tiktok_pet"), "kuaishou": ("tiktok_ai", "youtube_ai_scenario")}


# Collector metric names -> the names hot_viral_intelligence reads; values are copied unchanged.
METRIC_NAMES = {"view": "view_count", "like": "like_count", "comment": "comment_count", "reply": "comment_count",
                "share": "share_count", "repost": "repost_count", "favorite": "favorite_count", "danmaku": "danmaku"}


def _metrics(observed: Any) -> dict[str, Any]:
    observed = observed if isinstance(observed, dict) else {}
    named = {METRIC_NAMES[key]: value for key, value in observed.items() if key in METRIC_NAMES and value is not None}
    return {**observed, **named}


def _dimension(observed: Any, field: str) -> dict[str, Any] | None:
    return {"observed": observed, "field": field} if observed not in (None, "", [], {}) else None


def reference_samples(rows: list[dict[str, Any]], lane: str) -> list[dict[str, Any]]:
    """Hot/viral reference samples whose nine dimensions cite observed collector fields only.

    A row missing any dimension is left out; nothing is inferred from a title.
    """
    samples = []
    for row in rows:
        frames = [frame.get("description") for frame in row.get("visual_evidence") or [] if frame.get("description")]
        segments = [seg.get("text") for seg in (row.get("voiceover") or {}).get("segments") or [] if seg.get("text")]
        structure = row.get("content_structure") or {}
        transition = row.get("transition_combination") or {}
        breakdown = {
            "copy": _dimension(str(row.get("copy_or_script") or "")[:300], "copy_or_script"),
            "hook": _dimension(segments[0] if segments else (frames[0] if frames else ""),
                               "voiceover.segments[0]" if segments else "visual_evidence[0].description"),
            "writing_style": _dimension((row.get("writing_style") or {}).get("observed") or (row.get("writing_style") or {}).get("patterns"), "writing_style"),
            "illustration": _dimension(frames[:3], "visual_evidence[:3].description"),
            "cover": _dimension(frames[0] if frames else "", "visual_evidence[0].description"),
            "video_structure": _dimension(structure.get("observed") or structure.get("patterns"), "content_structure"),
            "motion": _dimension((row.get("motion_combination") or {}).get("observed"), "motion_combination.observed"),
            "transition": _dimension({"cuts_per_minute": transition.get("cuts_per_minute"), "observed": transition.get("observed")}
                                     if transition.get("cuts_per_minute") is not None else None, "transition_combination"),
            # The observed ending; it records what the work did, not a claimed CTA effect.
            "CTA": _dimension(segments[-1] if segments else (frames[-1] if frames else ""),
                              "voiceover.segments[-1]" if segments else "visual_evidence[-1].description"),
        }
        if any(value is None for value in breakdown.values()):
            continue
        samples.append({
            **{key: row.get(key) for key in ("platform", "source", "content_id", "canonical_url", "author", "published_at",
                                             "observed_at", "raw_response_hash")},
            "metrics": _metrics(row.get("metrics")),
            "lane": lane, "signal_type": "reference_work", "reference_use": "analysis_only_no_reuse",
            "content_evidence": {key: row.get(key) for key in ("title", "copy_or_script", "visual_evidence", "voiceover",
                                                               "content_structure", "motion_combination", "transition_combination")},
            "breakdown": breakdown,
        })
    return samples


def attach_breakdowns(prepared: dict[str, Any], items: list[dict[str, Any]], out_dir: str | Path) -> dict[str, Any]:
    from .task_source_inputs import _observed_strategy_inputs

    cache: dict[str, Any] = {}
    rows_by_collector: dict[str, Any] = {}
    failed: dict[str, str] = {}  # A collector that failed is not asked again in the same batch.
    for task in prepared.get("tasks") or []:
        platform = str(task.get("platform") or "")
        if task.get("state") != "ready_for_plan":
            continue
        if platform not in cache:
            errors = []
            for name, source_platform in [*filter(None, [NATIVE_COLLECTORS.get(platform)]),
                                          LANE_COLLECTORS.get(platform, (platform, platform)),
                                          *FALLBACK_COLLECTORS.get(platform, ())]:
                try:
                    if name not in COLLECTORS:
                        raise ValueError("no typed public same-lane collector for this platform")
                    if name in failed:
                        raise ValueError(failed[name])
                    if name not in rows_by_collector:  # Lanes sharing a collector observe once.
                        try:
                            rows_by_collector[name] = COLLECTORS[name](items, Path(out_dir))
                        except Exception as exc:
                            failed[name] = str(exc)[:200]
                            raise
                    cache[platform] = _observed_strategy_inputs(source_platform, {"items": rows_by_collector[name]})
                except Exception as exc:  # One platform's benchmark must not abort the batch.
                    errors.append(f"{name}: {str(exc)[:200]}")
                    continue
                if source_platform != platform:
                    cache[platform]["cross_platform_source"] = source_platform
                if errors:
                    cache[platform]["native_source_error"] = errors[0]
                break
            else:
                cache[platform] = {"error": "same-lane breakdown unavailable: " + "; ".join(errors)}
        strategy = cache[platform]
        if "error" in strategy:
            task.update(state="blocked", reason=strategy["error"])
            continue
        task.setdefault("brief", {}).update(strategy)
        if platform in REFERENCE_COLLECTORS:
            samples = []
            for name in REFERENCE_COLLECTORS[platform]:
                if name not in rows_by_collector:
                    if name in failed:
                        continue
                    try:
                        rows_by_collector[name] = COLLECTORS[name](items, Path(out_dir))
                    except Exception:  # A missing reference source shows up as fewer sources, not a crash.
                        rows_by_collector[name] = []
                samples += reference_samples(rows_by_collector[name], str(task["brief"].get("lane") or ""))
            task["brief"].update(hot_viral_samples=samples,
                                 hot_viral_source_statuses={sample["source"]: "ready" for sample in samples})
    return prepared
