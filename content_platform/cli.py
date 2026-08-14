import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .admin_server import make_admin_server
from .fusion import fusion_pipeline, format_content, format_for_channel, fetch_trends, council_review
from .intelligence import build_generation_context
from .niche_analysis import analyze_niche
from .metrics import render_metrics
from .seo import search as _seo_search, analyze as _seo_analyze, geo_checklist
from .paths import project_home
from .pipeline import Pipeline
from .project_audit import audit_project
from .profiles import resolve_profile
from .readiness import inspect_delivery_readiness
from .skills_adapter import fetch_hot_data, generate_content, get_status as skills_status
from .store import Store
from .task_market import TaskMarketRunner
from .trends import DirectTrendSource, TrendCollector, rank_trends


def _load_env_defaults(path: str | Path | None = None) -> str:
    """Load private KEY=VALUE defaults without overriding the process env."""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    env_override = os.environ.get("CONTENT_PLATFORM_PROXY_ENV_FILE", "").strip()
    if env_override:
        candidates.append(Path(env_override))
    home = project_home()
    candidates.extend(
        [
            home / "secrets" / "proxy.env",
            Path("secrets") / "proxy.env",
            Path("config") / "private" / "proxy.env",
        ]
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return str(candidate)
    return ""


def _load_collector_config(path: str | Path | None = None) -> tuple[dict, str]:
    """Load private performance collector settings from explicit or default paths."""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    env_override = os.environ.get("CONTENT_PLATFORM_PERFORMANCE_COLLECTOR_CONFIG", "").strip()
    if env_override:
        candidates.append(Path(env_override))
    home = project_home()
    candidates.extend(
        [
            home / "secrets" / "performance-collector.json",
            Path("secrets") / "performance-collector.json",
            Path("config") / "private" / "performance_collectors.json",
            Path("config") / "performance_collectors.json",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8")), str(candidate)
    return {}, ""


def load_config(path, db_path):
    config = {}
    if path and Path(path).is_file():
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    config.setdefault("data_dir", str(Path(db_path).parent))
    config.setdefault("generator", {"allow_fallback": True})
    config.setdefault("publishers", {"default": {"type": "file"}})
    return config


def parser():
    default_root = project_home()
    p = argparse.ArgumentParser(prog="content-platform", description="Hermes AI content workflow")
    p.add_argument("--db", default=str(default_root / "data" / "state.db"))
    p.add_argument("--config", default=str(default_root / "config.json"))
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    create = sub.add_parser("create")
    create.add_argument("--topic", required=True)
    create.add_argument("--platform", action="append", required=True)
    create.add_argument("--brief", default="{}", help="JSON object")
    create.add_argument("--profile", default="default")
    run = sub.add_parser("run")
    run.add_argument("job_id")
    run.add_argument("--force", action="store_true")
    approve = sub.add_parser("approve")
    approve.add_argument("job_id")
    approve.add_argument("--actor", required=True)
    approve.add_argument("--note", default="")
    reject = sub.add_parser("reject")
    reject.add_argument("job_id")
    reject.add_argument("--actor", required=True)
    reject.add_argument("--note", default="")
    publish = sub.add_parser("publish")
    publish.add_argument("job_id")
    status = sub.add_parser("status")
    status.add_argument("job_id")
    listing = sub.add_parser("list")
    listing.add_argument("--state")
    listing.add_argument("--limit", type=int, default=50)
    trends = sub.add_parser("trends")
    trends.add_argument("--refresh", action="store_true")
    trends.add_argument("--profile", default="default")
    trends.add_argument("--limit", type=int, default=20)
    trends.add_argument("--diagnostics", action="store_true", help="Include per-source trend collection status")
    auto = sub.add_parser("auto")
    auto.add_argument("--limit", type=int, default=3)
    auto.add_argument("--platform", action="append", help="目标平台（多次使用），不指定时用 --region 替代")
    auto.add_argument("--region", choices=["domestic", "international"], help="按地区选择平台，替代 --platform")
    auto.add_argument("--refresh", action="store_true")
    auto.add_argument("--profile", default="default")
    overnight_plan = sub.add_parser("overnight-plan", help="Build a serial, recoverable overnight batch plan")
    overnight_plan.add_argument("--tasks", required=True, help="JSON file containing a task list or {tasks: [...]} object")
    overnight_plan.add_argument("--output", required=True, help="Output JSON plan path")
    overnight_plan.add_argument("--start-minute", type=int, default=0)
    overnight_plan.add_argument("--deadline-minute", type=int, default=280)
    overnight_plan.add_argument("--finalization-minutes", type=int, default=20)
    overnight_prepare = sub.add_parser("overnight-prepare", help="Select one source-evidenced topic for each due channel slot")
    overnight_prepare.add_argument("--slots", required=True, help="Private JSON due-channel slot list")
    overnight_prepare.add_argument("--output", required=True, help="Prepared task JSON path")
    overnight_prepare.add_argument("--refresh", action="store_true")
    overnight_prepare.add_argument("--profile", default="default")
    overnight_prepare.add_argument("--weekday", type=int, choices=range(7), help="Optional Monday=0 schedule simulation; never used by the timer")
    overnight_run = sub.add_parser("overnight-run", help="Resume a planned overnight batch without implicit live publishing")
    overnight_run.add_argument("--plan", required=True, help="JSON plan created by overnight-plan")
    overnight_run.add_argument("--state", required=True, help="Persistent batch state path")
    overnight_run.add_argument("--events", required=True, help="Append-only JSONL event path")
    overnight_sync = sub.add_parser("overnight-sync-state", help="Reconcile a batch checkpoint from existing job records")
    overnight_sync.add_argument("--state", required=True, help="Batch state JSON path")
    overnight_sync.add_argument("--output", required=True, help="Acceptance summary JSON path")
    review_token = sub.add_parser("review-token")
    review_token.add_argument("job_id")
    review_token.add_argument("--action", choices=["approve", "reject"], required=True)
    review_action = sub.add_parser("review-action")
    review_action.add_argument("token")
    review_action.add_argument("--action", choices=["approve", "reject"], required=True)
    review_action.add_argument("--actor", required=True)
    review_action.add_argument("--note", default="")
    sub.add_parser("recover")
    maintenance = sub.add_parser("maintenance")
    maintenance.add_argument("--retention-days", type=int, default=14)
    metrics = sub.add_parser("metrics")
    metrics.add_argument("--output")
    performance = sub.add_parser("record-performance")
    performance.add_argument("job_id")
    performance.add_argument("--platform", required=True)
    performance.add_argument("--views", type=int, default=0)
    performance.add_argument("--likes", type=int, default=0)
    performance.add_argument("--comments", type=int, default=0)
    performance.add_argument("--shares", type=int, default=0)
    performance.add_argument("--saves", type=int, default=0)
    performance.add_argument("--follows", type=int, default=0)
    performance.add_argument("--completion-rate", type=float, default=0.0)
    performance.add_argument("--three-second-view-rate", type=float, default=0.0)
    performance.add_argument("--avg-watch-seconds", type=float, default=0.0)
    performance.add_argument("--metric", action="append", default=[], help="Extra platform metric as key=value, for example coin_rate=0.08")
    task_scan = sub.add_parser("task-market-scan")
    task_scan.add_argument("--env", choices=["cn", "intl"], default="cn")
    task_scan.add_argument("--page-size", type=int, default=20)
    task_auto = sub.add_parser("task-market-auto")
    task_auto.add_argument("--env", choices=["cn", "intl"], default="cn")
    task_auto.add_argument("--page-size", type=int, default=20)
    sub.add_parser("delivery-readiness")
    health_refresh = sub.add_parser("health-refresh")
    health_refresh.add_argument("--output", default="")
    health_refresh.add_argument("--platform", action="append")
    analyze = sub.add_parser("analyze-topic")
    analyze.add_argument("--topic", required=True)
    analyze.add_argument("--brief", default="{}", help="JSON object")
    account_report = sub.add_parser("account-report")
    account_report.add_argument("--topic", required=True)
    account_report.add_argument("--brief", default="{}", help="JSON object")
    sub.add_parser("content-readiness")
    cookie_inv = sub.add_parser("cookie-inventory")
    cookie_inv.add_argument("--platform", action="append")
    cookie_inv.add_argument("--account", default="main")
    cookie_inv.add_argument("--cookie-dir", default="")
    sub.add_parser("feedback-summary")
    perf_import = sub.add_parser("performance-import")
    perf_import.add_argument("file", help="JSON/JSONL metrics file with job_id, platform, and metric fields")
    perf_import.add_argument("--allow-unknown-job", action="store_true", help="Import records even when the job is not in this database")
    perf_review = sub.add_parser("performance-review")
    perf_review.add_argument("--output", default="", help="Optional JSON report output path")
    perf_review.add_argument("--platform", action="append", help="Expected platform to include even when metrics are missing")
    perf_collect = sub.add_parser("performance-collect")
    perf_collect.add_argument("--platform", action="append", required=True)
    perf_collect.add_argument("--collector-config", default="", help="JSON file with collector settings, for example YouTube channel_url or Bilibili mid")
    perf_collect.add_argument("--output", default="", help="Optional JSON collection report path")
    perf_collect.add_argument("--hermes-platform-scraper", action="store_true", help="Use the script configured by HERMES_PLATFORM_SCRAPER when available")
    perf_cycle = sub.add_parser("performance-cycle")
    perf_cycle.add_argument("--platform", action="append", help="Platform to include; defaults to growth-policy platforms")
    perf_cycle.add_argument("--collector-config", default="", help="Private JSON collector settings")
    perf_cycle.add_argument("--output-dir", default="", help="Directory for raw collection and review reports")
    perf_cycle.add_argument("--hermes-platform-scraper", action="store_true", help="Use HERMES_PLATFORM_SCRAPER bridge for the collection step")
    perf_source_audit = sub.add_parser("performance-source-audit")
    perf_source_audit.add_argument("--platform", action="append", required=True)
    perf_source_audit.add_argument("--collector-config", default="", help="Private JSON collector settings")
    perf_source_audit.add_argument("--output", default="", help="Optional JSON source coverage report path")
    metrics_readiness = sub.add_parser("metrics-readiness")
    metrics_readiness.add_argument("--platform", action="append", help="Platform to inspect; defaults to growth-policy platforms")
    metrics_readiness.add_argument("--collector-config", default="", help="Private JSON collector settings")
    metrics_readiness.add_argument("--output", default="", help="Optional JSON readiness report path")
    sub.add_parser("project-audit")
    sub.add_parser("health")
    admin = sub.add_parser("admin-serve")
    admin.add_argument("--password", required=True)
    admin.add_argument("--host", default="127.0.0.1")
    admin.add_argument("--port", type=int, default=0)
    worker = sub.add_parser("delivery-worker")
    worker.add_argument("--poll-interval", type=int, default=3)
    worker.add_argument("--batch-size", type=int, default=20)
    worker.add_argument("--once", action="store_true")
    gen_worker = sub.add_parser("generation-worker")
    gen_worker.add_argument("--poll-interval", type=int, default=3)
    gen_worker.add_argument("--batch-size", type=int, default=20)
    gen_worker.add_argument("--include-failed", action="store_true")
    gen_worker.add_argument("--once", action="store_true")
    seo_search = sub.add_parser("seo-search")
    seo_search.add_argument("--query", required=True)
    seo_search.add_argument("--engine", choices=["google", "bing", "duck", "baidu", "yandex", "ecosia"], default="duck")
    seo_search.add_argument("--limit", type=int, default=5)
    seo_analyze = sub.add_parser("seo-analyze")
    seo_analyze.add_argument("url")
    demo = sub.add_parser("demo")
    demo.add_argument("--actor", default="demo-operator")

    # v3.1 — SEO/GEO commands
    geo = sub.add_parser("seo-geo-check")
    geo.add_argument("file", help="Path to markdown content file, or '-' for stdin")
    kw = sub.add_parser("keyword-research")
    kw.add_argument("query", help="Search query for OpenSERP")
    kw.add_argument("--engine", default="duck", help="Search engine (duck, google, bing)")
    kw.add_argument("--limit", type=int, default=10)
    kw.add_argument("--endpoint", default="", help="OpenSERP instance URL")

    # v3.1 — Publish matrix command
    pub_matrix = sub.add_parser("publish-matrix")
    pub_matrix.add_argument("--matrix", default="", help="Matrix directory path")
    pub_matrix.add_argument("--platform", action="append", help="Target platform(s)")
    pub_matrix.add_argument("--dry-run", action="store_true", help="Show what would be published without sending")
        # v0.2 — RSS Ingest
    rss = sub.add_parser("rss-ingest")
    rss.add_argument("feed", nargs="+", help="RSS feed URLs")
    rss.add_argument("--topic", default="", help="Optional topic tag")
    # v0.2 — Schedule
    sub.add_parser("schedule-list")
    sc = sub.add_parser("schedule-create")
    sc.add_argument("--topic", required=True)
    sc.add_argument("--platform", action="append", required=True)
    sc.add_argument("--cron", default="@daily")
    sc.add_argument("--label", default="")
    # v0.2 — Newsletter
    nl = sub.add_parser("newsletter")
    nl.add_argument("feeds", nargs="+", help="RSS feed URLs")
    nl.add_argument("--keywords", nargs="*", default=[])
    nl.add_argument("--max", type=int, default=10)

    # v4.0 — WeWrite integration
    ww = sub.add_parser("wewrite", help="Run WeWrite workflow for WeChat article")
    ww.add_argument("action", choices=["hotspots", "topic", "article", "full"],
                    help="Action: hotspots=topic discovery, topic=scored topics, article=write draft, full=complete pipeline")
    ww.add_argument("--topic", default="", help="Topic for article action")
    ww.add_argument("--output", default="", help="Output path for generated article")
    explainer = sub.add_parser("article-video", help="Build an article-to-explainer-video package")
    explainer.add_argument("--input", required=True, help="Markdown article path")
    explainer.add_argument("--output-dir", required=True, help="Output directory for storyboard and plans")
    explainer.add_argument("--title", default="")
    explainer.add_argument("--pages", type=int, default=8)
    explainer.add_argument("--aspect-ratio", default="16:9")
    explainer.add_argument("--presenter-side", choices=["left", "right", "none"], default="right")
    viral = sub.add_parser("viral-monitor", help="Score collected platform works for growth decisions")
    viral.add_argument("--input", required=True, help="JSON file containing posts or {posts,recent_by_account}")
    viral.add_argument("--output", default="")
    return p


def _exec_wewrite(args, config):
    """Execute WeWrite workflow actions via CLI wrapper.

    Delegates to the wewrite CLI tool installed at ~/.local/bin/wewrite.
    """
    import subprocess, json
    wewrite_bin = os.path.expanduser("~/.local/bin/wewrite")
    if not os.path.exists(wewrite_bin):
        return {"ok": False, "error": "wewrite CLI not found at " + wewrite_bin}

    try:
        if args.action == "hotspots":
            r = subprocess.run([wewrite_bin, "hotspots", "--limit", "15"],
                              capture_output=True, text=True, timeout=45)
            if r.returncode != 0:
                return {"ok": False, "error": r.stderr[:300]}
            return {"ok": True, "hotspots": json.loads(r.stdout)}

        elif args.action == "topic":
            if not args.topic:
                return {"ok": False, "error": "wewrite topic requires --topic"}
            r = subprocess.run([wewrite_bin, "run", "start", "--topic", args.topic,
                               "--mode", "draft", "--visual-mode", "prompts", "--max-images", "3"],
                              capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "output": r.stdout[:500], "run_id": json.loads(r.stdout).get("run_id") if r.stdout and r.returncode == 0 else ""}

        elif args.action == "article":
            topic = args.topic or "今日热点"
            r = subprocess.run([wewrite_bin, "run", "start", "--topic", topic,
                               "--mode", "draft", "--visual-mode", "prompts", "--max-images", "3"],
                              capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return {"ok": False, "error": r.stderr[:300]}
            data = json.loads(r.stdout)
            return {"ok": True, "run_id": data.get("run_id"), "status": "draft_created"}

        elif args.action == "full":
            topic = args.topic or "今日热点"
            r = subprocess.run([wewrite_bin, "run", "start", "--topic", topic,
                               "--mode", "complete", "--visual-mode", "prompts", "--max-images", "3"],
                              capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return {"ok": False, "error": r.stderr[:300]}
            data = json.loads(r.stdout)
            return {"ok": True, "run_id": data.get("run_id"), "status": "full_pipeline_started"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "wewrite command timed out"}
    except json.JSONDecodeError:
        return {"ok": True, "note": "wewrite executed but response not JSON"}


def execute(args):
    import time
    from .formatters import format_for_platform
    store = Store(args.db)
    store.init()
    config = load_config(args.config, args.db)
    pipeline = Pipeline(store, config)
    if args.command == "init":
        return {"ok": True, "db": str(store.path), "version": __version__}
    if args.command == "seo-search":
        return _seo_search(args.query, args.engine, args.limit)
    if args.command == "seo-analyze":
        return _seo_analyze(args.url)
    if args.command == "create":
        brief = json.loads(args.brief)
        if not isinstance(brief, dict):
            raise ValueError("brief must be a JSON object")
        return pipeline.create(args.topic, args.platform, brief, args.profile)
    if args.command == "run":
        return pipeline.run(args.job_id, args.force)
    if args.command == "approve":
        return pipeline.approve(args.job_id, args.actor, args.note)
    if args.command == "reject":
        return pipeline.reject(args.job_id, args.actor, args.note)
    if args.command == "publish":
        return pipeline.publish(args.job_id)
    if args.command == "status":
        return pipeline.status(args.job_id)
    if args.command == "list":
        return store.list_jobs(args.limit, args.state)
    if args.command == "review-token":
        job = store.get_job(args.job_id)
        if job["state"] != "review_required":
            raise ValueError("review tokens require a review_required job")
        return {"job_id": args.job_id, "action": args.action, "token": pipeline.review_tokens.issue(args.job_id, args.action)}
    if args.command == "review-action":
        payload = pipeline.review_tokens.verify(args.token, args.action)
        if args.action == "approve":
            return pipeline.approve(payload["job_id"], args.actor, args.note)
        return pipeline.reject(payload["job_id"], args.actor, args.note)
    if args.command == "recover":
        return {"recovered": store.recover_stale()}
    if args.command == "maintenance":
        recovered = store.recover_stale()
        cleanup = pipeline.guard.cleanup(store.protected_paths(), args.retention_days)
        return {"recovered": recovered, **cleanup}
    if args.command == "metrics":
        content = render_metrics(store)
        output = Path(args.output) if args.output else Path(config["data_dir"]) / "metrics.prom"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        return {"output": str(output), "bytes": len(content.encode())}
    if args.command == "record-performance":
        store.get_job(args.job_id)
        extra_metrics = {}
        for item in args.metric:
            key, separator, value = str(item).partition("=")
            if not separator or not key.strip():
                raise ValueError("--metric must use key=value")
            try:
                extra_metrics[key.strip()] = float(value)
            except ValueError:
                extra_metrics[key.strip()] = value
        store.record_performance(
            args.job_id,
            args.platform,
            args.views,
            args.likes,
            args.comments,
            args.shares,
            saves=args.saves,
            follows=args.follows,
            completion_rate=args.completion_rate,
            three_second_view_rate=args.three_second_view_rate,
            avg_watch_seconds=args.avg_watch_seconds,
            extra_metrics=extra_metrics,
        )
        return {
            "job_id": args.job_id,
            "platform": args.platform,
            "views": args.views,
            "likes": args.likes,
            "comments": args.comments,
            "shares": args.shares,
            "saves": args.saves,
            "follows": args.follows,
            "completion_rate": args.completion_rate,
            "three_second_view_rate": args.three_second_view_rate,
            "avg_watch_seconds": args.avg_watch_seconds,
            "extra_metrics": extra_metrics,
        }
    if args.command == "task-market-scan":
        return TaskMarketRunner(args.db, config).scan(args.env, args.page_size)
    if args.command == "task-market-auto":
        return TaskMarketRunner(args.db, config).auto_run(args.env, args.page_size)
    if args.command == "delivery-readiness":
        return inspect_delivery_readiness(config)
    if args.command == "health-refresh":
        from .health_refresh import refresh_delivery_health
        output = args.output or str(Path(config.get("data_dir", Path(args.db).parent)) / "delivery_health_state.json")
        return refresh_delivery_health(config, output, args.platform)
    if args.command == "content-readiness":
        result = inspect_delivery_readiness(config)
        store.save_tool_inventory("content-tools", result.get("tools", {}).get("content_tools", {}))
        return result
    if args.command == "cookie-inventory":
        from .auth_registry import cookie_inventory
        platforms = args.platform or sorted((config.get("publishers") or {}).get("platforms") or {})
        return cookie_inventory(platforms, args.account, args.cookie_dir)
    if args.command == "feedback-summary":
        return store.feedback_summary()
    if args.command == "performance-import":
        from .performance_ingest import import_performance_file
        return import_performance_file(store, args.file, allow_unknown_job=args.allow_unknown_job)
    if args.command == "performance-review":
        from .performance_ingest import review_performance
        report = review_performance(store, expected_platforms=args.platform)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output"] = str(output)
        return report
    if args.command == "performance-collect":
        from .performance_collectors import collect_platform_metrics, collect_with_hermes_platform_scraper
        if args.hermes_platform_scraper:
            return collect_with_hermes_platform_scraper(args.platform, output=args.output or None)
        _load_env_defaults()
        collector_config, _collector_config_path = _load_collector_config(args.collector_config)
        return collect_platform_metrics(args.platform, collector_config, output=args.output or None)
    if args.command == "performance-cycle":
        from .performance_cycle import run_performance_cycle
        _load_env_defaults()
        collector_config, _collector_config_path = _load_collector_config(args.collector_config)
        return run_performance_cycle(
            store,
            platforms=args.platform,
            collector_config=collector_config,
            use_hermes_scraper=args.hermes_platform_scraper,
            output_dir=args.output_dir or None,
        )
    if args.command == "performance-source-audit":
        from .performance_cycle import _source_coverage
        _load_env_defaults()
        collector_config, _collector_config_path = _load_collector_config(args.collector_config)
        report = {"status": "ok", "source_coverage": _source_coverage(args.platform, collector_config)}
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output"] = str(output)
        return report
    if args.command == "metrics-readiness":
        from .performance_cycle import DEFAULT_GROWTH_PLATFORMS, metrics_readiness_report
        _load_env_defaults()
        collector_config, _collector_config_path = _load_collector_config(args.collector_config)
        report = metrics_readiness_report(args.platform or DEFAULT_GROWTH_PLATFORMS, collector_config)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output"] = str(output)
        return report
    if args.command == "project-audit":
        return audit_project(Path.cwd())
    if args.command == "wewrite":
        return _exec_wewrite(args, config)
    if args.command == "article-video":
        from .explainer_video import write_explainer_package
        return write_explainer_package(args.input, args.output_dir, args.title, args.pages, args.aspect_ratio, args.presenter_side)
    if args.command == "viral-monitor":
        from .viral_monitor import score_posts_file
        return score_posts_file(args.input, args.output)
    if args.command == "analyze-topic":
        brief = json.loads(args.brief)
        if not isinstance(brief, dict):
            raise ValueError("brief must be a JSON object")
        return build_generation_context(args.topic, brief)
    if args.command == "account-report":
        brief = json.loads(args.brief)
        if not isinstance(brief, dict):
            raise ValueError("brief must be a JSON object")
        return analyze_niche(args.topic, brief.get("reference_posts", []))
    if args.command == "overnight-plan":
        from .overnight_batch import build_batch_plan
        source = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
        tasks = source.get("tasks", []) if isinstance(source, dict) else source
        if not isinstance(tasks, list):
            raise ValueError("overnight task file must contain a list or a tasks list")
        plan = build_batch_plan(
            tasks,
            start_minute=args.start_minute,
            deadline_minute=args.deadline_minute,
            finalization_minutes=args.finalization_minutes,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return {"status": plan["status"], "output": str(output), "tasks": len(plan["tasks"])}
    if args.command == "overnight-prepare":
        from .overnight_batch import (
            build_due_tasks,
            candidate_matches_topic_keywords,
            candidate_matches_platform_language,
            growth_strategy_snapshot_status,
            topic_keywords_for_slot,
        )
        raw_slots = json.loads(Path(args.slots).read_text(encoding="utf-8"))
        slots = raw_slots.get("slots", raw_slots.get("tasks", [])) if isinstance(raw_slots, dict) else raw_slots
        if not isinstance(slots, list):
            raise ValueError("overnight slots file must contain a list or slots list")
        collector = TrendCollector(config.get("trends", {}))
        report = collector.collect_with_report(args.refresh)
        profile = resolve_profile(config.get("profiles", {}), args.profile)
        weekday = datetime.now().weekday() if args.weekday is None else args.weekday
        # Pet transport requires its own verified source.  A generic AI trend
        # feed must never be repurposed into a pet-account assignment.
        for slot in slots:
            platform = str(slot.get("platform") or "").casefold() if isinstance(slot, dict) else ""
            due_days = slot.get("weekdays") if isinstance(slot, dict) else None
            if platform != "douyin_pet" or (isinstance(due_days, list) and due_days and weekday not in {int(day) for day in due_days}):
                continue
            started = datetime.now()
            try:
                targeted = DirectTrendSource("douyin", {"enabled": True, "limit": 12, "timeout": 8, "query": "抖音 宠物 猫 狗 热门 短视频"}).collect()
                report.setdefault("items", []).extend(targeted)
                status = "ok" if targeted and not all(item.get("source_unavailable") for item in targeted) else "unavailable"
                report.setdefault("sources", []).append({"source": "douyin_pet_targeted", "status": status, "count": len(targeted), "elapsed_ms": int((datetime.now() - started).total_seconds() * 1000)})
            except Exception as exc:  # Preserve failed evidence; selection remains fail-closed.
                report.setdefault("sources", []).append({"source": "douyin_pet_targeted", "status": "failed", "count": 0, "error": str(exc)[:240]})
        strategy_status = growth_strategy_snapshot_status(
            store,
            [str(slot.get("platform") or "").casefold() for slot in slots if isinstance(slot, dict)],
        )

        def rank_for_platform(platform, items, slot):
            # Keep a candidate pool so the batch builder can reserve a unique
            # topic for each channel instead of duplicating the first trend.
            keywords = topic_keywords_for_slot(platform, slot, profile)
            lane_profile = {**profile, "keywords": keywords, "source_weights": {**profile.get("source_weights", {}), "douyin:web_search": 2}}
            # Filter after ranking against the full bounded collection.  A
            # small pre-filter pool can be filled by irrelevant high-score
            # headlines and hide valid lane-specific candidates.
            ranked = rank_trends(items, lane_profile, store.used_topics(platform), 200, store.learned_ranking_context(args.profile))
            return [
                candidate
                for candidate in ranked
                if candidate_matches_topic_keywords(candidate, keywords)
                and candidate_matches_platform_language(platform, candidate)
            ]

        def candidate_filter(platform, candidate, slot):
            keywords = topic_keywords_for_slot(platform, slot, profile)
            return (
                candidate_matches_topic_keywords(candidate, keywords)
                and candidate_matches_platform_language(platform, candidate)
            )

        prepared = build_due_tasks(
            slots,
            items=report.get("items", []),
            source_report=report.get("sources", []),
            rank_for_platform=rank_for_platform,
            candidate_filter=candidate_filter,
            growth_strategy_status=strategy_status,
            weekday=weekday,
            strict_trend_evidence=True,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(prepared, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "status": "prepared",
            "output": str(output),
            "tasks": len(prepared["tasks"]),
            "source_summary": report.get("summary", {}),
            "growth_strategy_status": strategy_status,
        }
    if args.command == "overnight-run":
        from .overnight_batch import BatchEventJournal, execute_batch
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        return execute_batch(pipeline, plan, state_path=args.state, journal=BatchEventJournal(args.events), store=store, require_acceptance=True)
    if args.command == "overnight-sync-state":
        from .overnight_batch import sync_batch_state
        state_path = Path(args.state)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        report = sync_batch_state(state, store, summary_path=args.output)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return report
    if args.command in {"trends", "auto"}:
        collector = TrendCollector(config.get("trends", {}))
        report = collector.collect_with_report(args.refresh)
        items = report["items"]
        profile = resolve_profile(config.get("profiles", {}), args.profile)
        platforms = list(getattr(args, "platform", None) or [])
        if args.command == "auto" and args.region:
            from .publishers import domestic_platforms, international_platforms
            region_platforms = domestic_platforms() if args.region == "domestic" else international_platforms()
            existing = set(platforms)
            for p in region_platforms:
                if p not in existing:
                    platforms.append(p)
        if args.command == "auto" and not platforms:
            raise ValueError("must specify --platform or --region")
        if args.command == "trends":
            items = rank_trends(items, profile, set(), args.limit, store.learned_ranking_context(args.profile))
            if args.diagnostics:
                return {**report, "ranked": items}
            return items
        from .overnight_batch import growth_strategy_snapshot_status
        strategy_status = growth_strategy_snapshot_status(store, platforms)
        jobs = []
        # A platform is a separate operating decision, not a bulk destination
        # for one trend.  Keep independent topic history and the raw source
        # collection result in every generated job.
        for platform in platforms:
            strategy = strategy_status.get(str(platform).casefold()) or {}
            if strategy.get("status") in {"missing", "stale"}:
                jobs.append(
                    {
                        "platform": platform,
                        "state": "blocked",
                        "last_error": f"growth strategy snapshot {strategy['status']}",
                        "growth_strategy_key": strategy.get("key", ""),
                    }
                )
                continue
            ranked = rank_trends(
                items,
                profile,
                store.used_topics(platform),
                args.limit,
                store.learned_ranking_context(args.profile),
            )
            source_matrix = {
                "platform": platform,
                "attempted_sources": [
                    {"source": row.get("source"), "status": row.get("status", "unknown"), **({"error": row["error"]} if row.get("error") else {})}
                    for row in report.get("sources", [])
                    if row.get("source")
                ],
                "report_path": "runtime:trend_collection_report",
            }
            for item in ranked:
                sources = [item["url"]] if item.get("url") else []
                brief = {
                    "source": item.get("source"),
                    "sources": sources,
                    "platform_source_matrix": source_matrix,
                    "topic_decision": {
                        "score": item.get("score", 0),
                        "signals": ["timeliness"] if item.get("trend_stage") in {"hot", "viral_candidate"} else ["user_benefit"],
                    },
                }
                job = pipeline.create(item["title"], [platform], brief, args.profile, item["fingerprint"])
                result = pipeline.run(job["id"])
                if result.get("state") not in {"blocked", "failed", "rejected"}:
                    store.mark_topic_used(item["fingerprint"], item["title"], item.get("source", ""), job["id"], platform=platform)
                jobs.append(result)
        return jobs
    if args.command == "health":
        with store.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "ok": True,
            "version": __version__,
            "db": str(store.path),
            "live_publish": os.environ.get("CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH") == "1",
            "resources": pipeline.guard.probe(),
        }
    if args.command == "admin-serve":
        server = make_admin_server(store.path, args.password, args.host, args.port, config=config)
        print(json.dumps({"ok": True, "access_url": server.launch_url, "host": args.host, "port": server.server_port}, ensure_ascii=False))
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return {"ok": True, "stopped": True}
    if args.command == "delivery-worker":
        processed = pipeline.process_delivery_queue(args.batch_size) if args.once else pipeline.process_delivery_queue_forever(args.poll_interval, args.batch_size)
        return {"ok": True, "processed": processed}
    if args.command == "generation-worker":
        processed = (
            pipeline.process_generation_queue(args.batch_size, args.include_failed)
            if args.once
            else pipeline.process_generation_queue_forever(args.poll_interval, args.batch_size, args.include_failed)
        )
        return {"ok": True, "processed": processed}
    if args.command == "demo":
        job = pipeline.create("Hermes content platform offline acceptance", ["demo"], {"audience": "Hermes operator"})
        pipeline.run(job["id"])
        pipeline.approve(job["id"], args.actor, "offline acceptance")
        return pipeline.publish(job["id"])

    # ── v3.1: SEO/GEO commands ──
    if args.command == "seo-geo-check":
        from .seo import geo_check, format_geo_report
        if args.file == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.file).read_text(encoding="utf-8")
        # Strip YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end+3:].strip()
        result = geo_check(text)
        report = format_geo_report(text, Path(args.file).name if args.file != "-" else "stdin")
        print(report)
        return result

    if args.command == "keyword-research":
        from .seo import openserp_search
        result = openserp_search(args.query, args.engine, args.limit, args.endpoint)
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        print(f"\n## 关键词: {result['query']}")
        print(f"引擎: {result['engine']}  |  结果数: {result['result_count']}")
        print(f"SERP类型: {result['serp_types']}")
        print()
        for r in result.get("results", []):
            print(f"  • [{r['title']}]({r['url']})")
            if r.get("snippet"):
                print(f"    {r['snippet'][:100]}")
        if result.get("people_also_ask"):
            print(f"\n**People Also Ask ({len(result['people_also_ask'])}):**")
            for q in result["people_also_ask"]:
                print(f"  - {q}")
        if result.get("content_gaps"):
            print(f"\n**内容空白 ({len(result['content_gaps'])}):**")
            for g in result["content_gaps"]:
                print(f"  ⚠️ {g}")
        return result

    # ── v3.1: Publish matrix ──
    if args.command == "publish-matrix":
        from .copy_manager import CopyMatrix

        matrix_dir = args.matrix or os.environ.get("CONTENT_PLATFORM_MATRIX", "")
        if not matrix_dir:
            # Fall back to default matrix path
            matrix_dir = str(Path(config.get("data_dir", "/tmp")) / "matrix")
            Path(matrix_dir).mkdir(parents=True, exist_ok=True)

        matrix = CopyMatrix(matrix_dir)
        copies = matrix.load_all_copies()
        if not copies:
            return {"ok": False, "error": f"no copy files found in {matrix_dir}/copy/"}

        platforms = args.platform if args.platform else list(matrix.load_content_rules().get("channel_rules", {}).keys())
        if not platforms:
            # Default platform list for matrix publishing
            platforms = ["devto", "mastodon", "bluesky", "telegraph", "nostr", "writeas"]

        results = []
        for fname, content in copies.items():
            for plat in platforms:
                if args.dry_run:
                    results.append({"platform": plat, "copy": fname, "action": "dry-run", "ok": True})
                    continue
                error = "publish-matrix live publishing is disabled; create a Pipeline job so workflow locks, gates, receipts, postchecks, and reports run"
                results.append({"platform": plat, "copy": fname, "ok": False, "status": "blocked", "error": error})
                matrix.log_publish(plat, False, "", error)

        success = sum(1 for r in results if r.get("ok"))
        print(f"publish results: {success}/{len(results)}")
        for r in results:
            icon = "OK" if r.get("ok") else "FAIL"
            print(f"  {icon} {r['platform']} | {r.get('copy','')}")
        return {"success": success, "total": len(results), "results": results}

    if args.command == "rss-ingest":
        from .rss_ingest import ingest_multi
        return ingest_multi(args.feed, store)
    if args.command == "schedule-list":
        from .scheduler import list_schedules
        return {"schedules": list_schedules(store)}
    if args.command == "schedule-create":
        from .scheduler import schedule_job
        return schedule_job(store, args.topic, args.platform, cron=args.cron, label=args.label or args.topic)
    if args.command == "newsletter":
        from .newsletter import pipeline as newsletter_pipeline
        from .paths import project_home
        return newsletter_pipeline(args.feeds, keywords=args.keywords, max_selected=args.max,
                                   config={"data_dir": str(project_home() / "data")})
    raise ValueError(f"unsupported command: {args.command}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass
    try:
        result = execute(parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, PermissionError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
