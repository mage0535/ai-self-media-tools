"""Daily performance collection and growth-strategy refresh."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .growth_policy import build_growth_strategy
from .performance_collectors import collect_platform_metrics, collect_with_hermes_platform_scraper
from .performance_ingest import review_performance

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_PATH = ROOT / "config" / "channel_content_rulebook.json"


DEFAULT_GROWTH_PLATFORMS = [
    "wechat",
    "kuaishou",
    "bilibili",
    "zhihu",
    "juejin",
    "douyin",
    "shipinhao",
    "xiaohongshu",
    "youtube",
    "tiktok",
    "x",
]


def run_performance_cycle(
    store: Any,
    *,
    platforms: list[str] | None = None,
    collector_config: dict[str, Any] | None = None,
    use_hermes_scraper: bool = False,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Collect metrics, persist usable snapshots, and refresh growth strategies.

    The cycle is intentionally read/write-only for analytics. It never creates
    publish jobs, uploads content, or changes platform login state.
    """
    selected = _normalize_platforms(platforms or DEFAULT_GROWTH_PLATFORMS)
    out_dir = Path(output_dir or os.environ.get("CONTENT_PLATFORM_PERFORMANCE_DIR", "data/performance"))
    out_dir.mkdir(parents=True, exist_ok=True)
    collected = collect_platform_metrics(selected, collector_config or {}, output=out_dir / "raw_collect.json")
    if use_hermes_scraper:
        hermes_collected = collect_with_hermes_platform_scraper(selected, output=out_dir / "raw_collect_hermes.json")
        collected = _merge_collection_reports(collected, hermes_collected)
    persisted = _persist_collection(store, collected)
    review = review_performance(store, expected_platforms=selected)
    strategies = _refresh_growth_strategies(store, selected)
    source_coverage = _source_coverage(selected, collector_config or {})
    metrics_readiness = metrics_readiness_report(selected, collector_config or {})
    full_cycle = _is_full_cycle(selected)
    report = {
        "status": "ok",
        "cycle_scope": "full" if full_cycle else "partial",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": selected,
        "collection": collected,
        "persisted": persisted,
        "review": review,
        "growth_strategies": strategies,
        "source_coverage": source_coverage,
        "metrics_readiness": metrics_readiness,
        "activity": _activity_summary(collected, persisted, review),
    }
    report_path = out_dir / ("performance_cycle_report.json" if full_cycle else f"performance_cycle_{_platform_slug(selected)}.json")
    report["output"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    store.save_tool_inventory("performance_cycle_latest", {"report_path": str(report_path), **report})
    if full_cycle:
        store.save_tool_inventory("performance_cycle_full_latest", {"report_path": str(report_path), **report})
    return report


def _merge_collection_reports(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    merged["sources"] = [primary.get("source", "platform_collectors"), fallback.get("source", "hermes_platform_scraper")]
    merged_platforms = dict(primary.get("platforms") or {})
    for platform, item in (fallback.get("platforms") or {}).items():
        current = merged_platforms.get(platform) or {}
        current_has_metrics = current.get("status") in {"ok", "backend_signal", "public_signal"} and bool(current.get("account_metrics") or current.get("metrics"))
        fallback_has_metrics = item.get("status") in {"ok", "backend_signal", "public_signal"} and bool(item.get("account_metrics") or item.get("metrics"))
        if fallback_has_metrics and not current_has_metrics:
            fallback_item = dict(item)
            metric_key = "account_metrics" if isinstance(fallback_item.get("account_metrics"), dict) else "metrics"
            metrics = dict(fallback_item.get(metric_key) or {})
            extra = dict(metrics.get("extra_metrics") or {})
            # A generic Hermes scraper reports an account-page observation,
            # not a per-content export. Keep it available for audit but never
            # let it steer ranking or the next content direction.
            extra.setdefault("metric_source", "hermes_platform_scraper")
            extra.setdefault("metric_confidence", "low")
            extra.setdefault("metric_scope", "account_snapshot")
            extra.setdefault("strategy_eligible", False)
            metrics["extra_metrics"] = extra
            fallback_item[metric_key] = metrics
            merged_platforms[platform] = fallback_item
    merged["platforms"] = merged_platforms
    if primary.get("status") != "ok" and fallback.get("status") == "ok":
        merged["status"] = "ok"
    return merged


def _normalize_platforms(platforms: list[str]) -> list[str]:
    result = []
    seen = set()
    for platform in platforms:
        value = str(platform or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _is_full_cycle(platforms: list[str]) -> bool:
    return list(platforms) == DEFAULT_GROWTH_PLATFORMS


def _platform_slug(platforms: list[str]) -> str:
    slug = "_".join(re.sub(r"[^a-zA-Z0-9_-]+", "-", str(platform).strip().lower()) for platform in platforms if str(platform).strip())
    return slug[:120] or "partial"


def _persist_collection(store: Any, collected: dict[str, Any]) -> dict[str, Any]:
    result = {"saved": 0, "unavailable": 0, "items": []}
    date_key = datetime.now(timezone.utc).date().isoformat()
    for platform, item in (collected.get("platforms") or {}).items():
        metrics = _flatten_metrics(item.get("account_metrics") or item.get("metrics") or {})
        status = str(item.get("status") or "")
        if status in {"ok", "backend_signal", "public_signal"} and metrics and _has_core_metrics(platform, metrics) and not _is_suspicious_platform_metrics(platform, metrics):
            if status != "ok":
                metrics.setdefault("extra_metrics", {})["metric_status"] = status
            job = _snapshot_job(store, platform, date_key)
            store.record_performance(
                job["id"],
                platform,
                views=int(metrics.get("views", 0)),
                likes=int(metrics.get("likes", 0)),
                comments=int(metrics.get("comments", 0)),
                shares=int(metrics.get("shares", 0)),
                saves=int(metrics.get("saves", 0)),
                follows=int(metrics.get("follows", 0)),
                completion_rate=float(metrics.get("completion_rate", 0.0)),
                three_second_view_rate=float(metrics.get("three_second_view_rate", 0.0)),
                avg_watch_seconds=float(metrics.get("avg_watch_seconds", 0.0)),
                extra_metrics=metrics.get("extra_metrics", {}),
            )
            strategy_eligible = metrics.get("extra_metrics", {}).get("strategy_eligible") is not False
            result["saved"] += 1
            result["items"].append(
                {
                    "platform": platform,
                    "status": "saved" if strategy_eligible else "saved_snapshot_only",
                    "job_id": job["id"],
                    "metrics": metrics,
                }
            )
        else:
            result["unavailable"] += 1
            reason = str(item.get("reason") or item.get("next_action") or "")[:300]
            if status in {"ok", "backend_signal", "public_signal"} and metrics and not _has_core_metrics(platform, metrics):
                status = "metrics_insufficient"
                reason = "collector returned only weak/non-growth metrics; not persisted to strategy"
            elif status in {"ok", "backend_signal", "public_signal"} and metrics and _is_suspicious_platform_metrics(platform, metrics):
                status = "metrics_suspicious"
                reason = "collector returned platform-known placeholder or page chrome numbers; not persisted to strategy"
            result["items"].append(
                {
                    "platform": platform,
                    "status": status or "unavailable",
                    "reason": reason,
                }
            )
    return result


def _snapshot_job(store: Any, platform: str, date_key: str) -> dict[str, Any]:
    fingerprint = f"performance-snapshot:{platform}:{date_key}"
    for job in store.list_jobs(500):
        if job.get("topic_fingerprint") == fingerprint:
            return job
    return store.create_job(
        f"Daily performance snapshot {platform} {date_key}",
        [platform],
        {"source": "performance_cycle", "date": date_key, "analytics_only": True},
        topic_fingerprint=fingerprint,
    )


def _flatten_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
        "follows": 0,
        "completion_rate": 0.0,
        "three_second_view_rate": 0.0,
        "avg_watch_seconds": 0.0,
        "extra_metrics": {},
    }
    aliases = {
        "views": "views",
        "view_count": "views",
        "play_count": "views",
        "plays": "views",
        "read_count": "views",
        "reads": "views",
        "subscribers": "follows",
        "followers": "follows",
        "fans": "follows",
        "likes": "likes",
        "comments": "comments",
        "shares": "shares",
        "saves": "saves",
        "favorites": "saves",
        "completion_rate": "completion_rate",
        "three_second_view_rate": "three_second_view_rate",
        "avg_watch_seconds": "avg_watch_seconds",
    }
    for key, value in metrics.items():
        if key == "extra_metrics" and isinstance(value, dict):
            flat["extra_metrics"].update(value)
            continue
        target = aliases.get(str(key))
        numeric = _number(value)
        if target in {"views", "likes", "comments", "shares", "saves", "follows"}:
            flat[target] += int(numeric)
        elif target in {"completion_rate", "three_second_view_rate", "avg_watch_seconds"}:
            flat[target] = float(numeric)
        elif numeric or isinstance(value, (int, float)):
            flat["extra_metrics"][str(key)] = numeric
    return flat


def _has_core_metrics(platform: str, metrics: dict[str, Any]) -> bool:
    if platform == "tiktok":
        return any(float(metrics.get(field, 0) or 0) > 0 for field in ("views", "likes", "comments", "shares", "completion_rate", "three_second_view_rate", "avg_watch_seconds"))
    if platform == "bilibili":
        return any(float(metrics.get(field, 0) or 0) > 0 for field in ("views", "follows", "completion_rate", "avg_watch_seconds"))
    core_fields = ("views", "likes", "comments", "shares", "saves", "follows", "completion_rate", "three_second_view_rate", "avg_watch_seconds")
    return any(float(metrics.get(field, 0) or 0) > 0 for field in core_fields)


def _is_suspicious_platform_metrics(platform: str, metrics: dict[str, Any]) -> bool:
    extra = metrics.get("extra_metrics") or {}
    source = str(extra.get("metric_source") or "").casefold()
    works = float(extra.get("works", 0) or 0)
    views = float(metrics.get("views", 0) or 0)
    likes = float(metrics.get("likes", 0) or 0)
    comments = float(metrics.get("comments", 0) or 0)
    shares = float(metrics.get("shares", 0) or 0)
    saves = float(metrics.get("saves", 0) or 0)
    engagement = likes + comments + shares + saves
    if "creator_backend_page" in source:
        # Browser backend scrapes can accidentally capture page chrome, dates,
        # or unrelated counters. Treat impossible account-scale combinations as
        # unusable so growth strategy does not learn from bogus numbers.
        if platform in {"xiaohongshu", "rednote", "zhihu", "juejin", "kuaishou"} and works > 10000:
            return True
        if views >= 1_000_000 and engagement < 1000:
            return True
        if views >= 1_000_000 and likes < 1000 and comments > max(1000, likes * 20):
            return True
        if views and engagement > views * 1.5:
            return True
    if platform == "tiktok":
        follows = float(metrics.get("follows", 0) or 0)
        if not views and saves and engagement <= 5:
            return True
        if views and views == follows == works and engagement <= 50:
            return True
    return False


def _number(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("period_total") or value.get("total") or value.get("value") or 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _refresh_growth_strategies(store: Any, platforms: list[str]) -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    account_variants = _load_platform_account_variants()
    for platform in platforms:
        historical = store.historical_performance([platform], "")
        content_type = "knowledge_card_video" if platform in {"douyin", "kuaishou", "shipinhao", "bilibili", "youtube"} else "long_article"
        if platform == "xiaohongshu":
            content_type = "image_text_knowledge_card_short_video_mix"
        strategy = build_growth_strategy([platform], content_type, historical)
        strategies[platform] = strategy
        store.save_tool_inventory(f"growth_strategy:{platform}:latest", strategy)
        for account_key, account in _account_variants_for_platform(account_variants, platform).items():
            # Account variants must earn their own history. Falling back to a
            # platform-wide aggregate leaks one account's performance into
            # another account's lane and creates false optimization signals.
            account_history = store.historical_performance([account_key], "")
            account_strategy = build_growth_strategy([platform], content_type, account_history)
            account_strategy.update(
                {
                    "account_key": account_key,
                    "base_platform": platform,
                    "lane": account.get("lane", ""),
                    "account_direction": account.get("account_direction", ""),
                    "publish_boundary": account.get("publish_boundary", ""),
                    "strategy_scope": "platform_account_variant",
                }
            )
            strategies[account_key] = account_strategy
            store.save_tool_inventory(f"growth_strategy:{account_key}:latest", account_strategy)
    return strategies


def _load_platform_account_variants() -> dict[str, Any]:
    try:
        rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    variants = rulebook.get("platform_account_variants") if isinstance(rulebook, dict) else {}
    return variants if isinstance(variants, dict) else {}


def _account_variants_for_platform(variants: dict[str, Any], platform: str) -> dict[str, Any]:
    platform_variants = variants.get(platform) if isinstance(variants, dict) else {}
    accounts = platform_variants.get("accounts") if isinstance(platform_variants, dict) else {}
    return accounts if isinstance(accounts, dict) else {}


def _source_coverage(platforms: list[str], collector_config: dict[str, Any]) -> dict[str, Any]:
    public_keys = {"public_profile_url", "profile_url", "homepage_url", "public_url", "public_urls"}
    backend_keys = {"state_file", "cookie_file", "datacube", "app_id", "channel_url", "mid", "uid", "metrics_file", "analytics_file"}
    items: dict[str, Any] = {}
    for platform in platforms:
        cfg = collector_config.get(platform, {}) if isinstance(collector_config.get(platform, {}), dict) else {}
        public = sorted(key for key in public_keys if cfg.get(key))
        backend = sorted(key for key in backend_keys if cfg.get(key))
        if not backend and not public:
            status = "missing_source"
        elif backend and not public and platform not in {"wechat", "bilibili", "youtube"}:
            status = "backend_only"
        else:
            status = "configured"
        items[platform] = {
            "status": status,
            "backend_sources": backend,
            "public_fallback_sources": public,
        }
    needs_attention = [platform for platform, item in items.items() if item["status"] in {"missing_source", "backend_only"}]
    return {
        "platforms": items,
        "missing_source_count": sum(1 for item in items.values() if item["status"] == "missing_source"),
        "backend_only_without_public_fallback_count": sum(1 for item in items.values() if item["status"] == "backend_only"),
        "needs_attention": needs_attention,
    }


def metrics_readiness_report(platforms: list[str], collector_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report whether each account has evidence suitable for strategy learning.

    A configured browser state alone proves neither account identity nor
    content-level metrics. Account variants therefore need their own source;
    a base-platform source is intentionally audit-only.
    """
    config = collector_config or {}
    selected = _normalize_platforms(platforms)
    variants = _load_platform_account_variants()
    accounts: dict[str, Any] = {}

    def source_status(source_config: dict[str, Any]) -> tuple[str, str, bool]:
        metrics_path = str(source_config.get("metrics_file") or source_config.get("analytics_file") or "").strip()
        api_configured = bool(source_config.get("api_url") or source_config.get("analytics_api_url"))
        if api_configured:
            return "content_metrics_configured", "approved content metrics API is configured", True
        if not metrics_path:
            return "account_source_missing", "configure an account-specific metrics export/API", False
        path = Path(metrics_path)
        if not path.is_file():
            return "metrics_file_missing", "configured metrics file is not available at runtime", False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "metrics_file_invalid", "configured metrics file is not valid JSON", False
        rows = payload.get("videos") if isinstance(payload, dict) else payload
        identifiers = {"job_id", "content_id", "item_id", "video_id", "post_id", "article_id", "work_id", "title", "work_title", "标题"}
        identified = isinstance(rows, list) and any(
            isinstance(row, dict) and any(str(row.get(field) or "").strip() for field in identifiers)
            for row in rows
        )
        if not identified:
            return "content_identity_missing", "metrics export has no title or stable content identifier", False
        if isinstance(rows, list):
            suspicious = 0
            checked = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                values = [row.get(key) for key in ("views", "followers", "works", "作品数", "播放量", "粉丝数")]
                numeric = [str(value).strip() for value in values if value not in (None, "")]
                if len(numeric) >= 3:
                    checked += 1
                    if len(set(numeric)) == 1:
                        suspicious += 1
            if checked and suspicious == checked:
                return "metrics_schema_suspicious", "views, followers, and works are identical across all rows", False
        return "content_metrics_configured", "content-level metrics export is configured", True

    for platform in selected:
        base_cfg = config.get(platform, {}) if isinstance(config.get(platform), dict) else {}
        variant_accounts = _account_variants_for_platform(variants, platform)
        if variant_accounts:
            accounts[platform] = {
                "platform": platform,
                "status": "base_platform_not_strategy_eligible",
                "reason": "base platform metrics cannot be attributed to a required account variant",
                "strategy_eligible": False,
            }
            account_cfgs = config.get(f"{platform}_accounts", {})
            account_cfgs = account_cfgs if isinstance(account_cfgs, dict) else {}
            for account_key in variant_accounts:
                account_cfg = account_cfgs.get(account_key, {})
                account_cfg = account_cfg if isinstance(account_cfg, dict) else {}
                status, reason, has_content_source = source_status(account_cfg)
                has_state = bool(account_cfg.get("state_file") or account_cfg.get("cookie_file"))
                accounts[account_key] = {
                    "platform": platform,
                    "account_key": account_key,
                    "status": status,
                    "reason": reason if has_content_source else f"{reason}; a shared base-platform state is not sufficient",
                    "state_configured": has_state,
                    "strategy_eligible": has_content_source,
                }
            continue
        status, reason, has_content_source = source_status(base_cfg)
        accounts[platform] = {
            "platform": platform,
            "status": status if has_content_source or status != "account_source_missing" else "account_snapshot_only",
            "reason": reason if has_content_source or status != "account_source_missing" else "browser/public account snapshots remain audit-only until content-level metrics are available",
            "strategy_eligible": has_content_source,
        }
    eligible = sum(1 for item in accounts.values() if item.get("strategy_eligible"))
    return {
        "status": "ok",
        "accounts": accounts,
        "summary": {
            "account_count": len(accounts),
            "strategy_eligible_count": eligible,
            "action_needed_count": len(accounts) - eligible,
        },
    }


def _activity_summary(collected: dict[str, Any], persisted: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    platforms = collected.get("platforms") or {}
    return {
        "collector_ran": collected.get("status") == "ok",
        "platform_count": len(platforms),
        "metrics_saved": int(persisted.get("saved", 0) or 0),
        "unavailable_count": int(persisted.get("unavailable", 0) or 0),
        "review_platform_count": len(review.get("platforms") or {}),
        "healthy": collected.get("status") == "ok" and len(platforms) > 0,
    }
