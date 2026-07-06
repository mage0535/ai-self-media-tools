import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
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
from .store import Store
from .task_market import TaskMarketRunner
from .trends import TrendCollector, rank_trends


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
    auto = sub.add_parser("auto")
    auto.add_argument("--limit", type=int, default=3)
    auto.add_argument("--platform", action="append", help="目标平台（多次使用），不指定时用 --region 替代")
    auto.add_argument("--region", choices=["domestic", "international"], help="按地区选择平台，替代 --platform")
    auto.add_argument("--refresh", action="store_true")
    auto.add_argument("--profile", default="default")
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
    task_scan = sub.add_parser("task-market-scan")
    task_scan.add_argument("--env", choices=["cn", "intl"], default="cn")
    task_scan.add_argument("--page-size", type=int, default=20)
    task_auto = sub.add_parser("task-market-auto")
    task_auto.add_argument("--env", choices=["cn", "intl"], default="cn")
    task_auto.add_argument("--page-size", type=int, default=20)
    sub.add_parser("delivery-readiness")
    analyze = sub.add_parser("analyze-topic")
    analyze.add_argument("--topic", required=True)
    analyze.add_argument("--brief", default="{}", help="JSON object")
    account_report = sub.add_parser("account-report")
    account_report.add_argument("--topic", required=True)
    account_report.add_argument("--brief", default="{}", help="JSON object")
    sub.add_parser("content-readiness")
    sub.add_parser("feedback-summary")
    sub.add_parser("project-audit")
    sub.add_parser("health")
    seo_search = sub.add_parser("seo-search")
    seo_search.add_argument("--query", required=True)
    seo_search.add_argument("--engine", choices=["google", "bing", "duck", "baidu", "yandex", "ecosia"], default="duck")
    seo_search.add_argument("--limit", type=int, default=5)
    seo_analyze = sub.add_parser("seo-analyze")
    seo_analyze.add_argument("url")
    seo_geo = sub.add_parser("seo-geo-check")
    seo_geo.add_argument("job_id")
    demo = sub.add_parser("demo")
    demo.add_argument("--actor", default="demo-operator")

    # ─── 7-project fusion subcommands ───
    fusion_p = sub.add_parser("fusion")
    fusion_sp = fusion_p.add_subparsers(dest="fusion_cmd", required=True)
    fusion_sp.add_parser("trend").add_argument("--topic", required=True)
    ff = fusion_sp.add_parser("format")
    ff.add_argument("--template", default="article", choices=["article","xiaohongshu","twitter","poster","deck"])
    ff.add_argument("--input")
    fr = fusion_sp.add_parser("review")
    fr.add_argument("--input")
    fa = fusion_sp.add_parser("all")
    fa.add_argument("--topic", required=True)
    fa.add_argument("--channel", default="wechat")

    return p


def execute(args):
    if args.command == "fusion":
        if args.fusion_cmd == "trend":
            data = fetch_trends(args.topic)
            return data or {"error": "trend fetch failed (cli not available?)"}
        elif args.fusion_cmd == "format":
            content = sys.stdin.read() if not args.input else Path(args.input).read_text(encoding="utf-8")
            result = format_content(content, args.template)
            if result:
                print(result)
                return {"ok": True, "bytes": len(result)}
            return {"error": "format failed"}
        elif args.fusion_cmd == "review":
            content = sys.stdin.read() if not args.input else Path(args.input).read_text(encoding="utf-8")
            return council_review(content)
        elif args.fusion_cmd == "all":
            return fusion_pipeline(args.topic, args.channel)

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
    if args.command == "seo-geo-check":
        job = store.get_job(args.job_id)
        return geo_checklist(job)
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
        store.record_performance(args.job_id, args.platform, args.views, args.likes, args.comments, args.shares)
        return {"job_id": args.job_id, "platform": args.platform, "views": args.views, "likes": args.likes, "comments": args.comments, "shares": args.shares}
    if args.command == "task-market-scan":
        return TaskMarketRunner(args.db, config).scan(args.env, args.page_size)
    if args.command == "task-market-auto":
        return TaskMarketRunner(args.db, config).auto_run(args.env, args.page_size)
    if args.command == "delivery-readiness":
        return inspect_delivery_readiness(config)
    if args.command == "content-readiness":
        result = inspect_delivery_readiness(config)
        store.save_tool_inventory("content-tools", result.get("tools", {}).get("content_tools", {}))
        return result
    if args.command == "feedback-summary":
        return store.feedback_summary()
    if args.command == "project-audit":
        return audit_project(Path.cwd())
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
    if args.command in {"trends", "auto"}:
        items = TrendCollector(config.get("trends", {})).collect(args.refresh)
        profile = resolve_profile(config.get("profiles", {}), args.profile)
        items = rank_trends(items, profile, store.used_topics(), args.limit)
        if args.command == "trends":
            return items
        jobs = []
        for item in items:
            sources = [item["url"]] if item.get("url") else []
            # 合并 --region 和 --platform 指定的平台列表
            platforms = list(args.platform or [])
            if args.region:
                from .publishers import domestic_platforms, international_platforms
                region_platforms = domestic_platforms() if args.region == "domestic" else international_platforms()
                # 去重合并：--region 为基础，--platform 可额外补充
                existing = set(platforms)
                for p in region_platforms:
                    if p not in existing:
                        platforms.append(p)
            if not platforms:
                raise ValueError("must specify --platform or --region")
            job = pipeline.create(
                item["title"], platforms, {"source": item.get("source"), "sources": sources}, args.profile, item["fingerprint"]
            )
            store.mark_topic_used(item["fingerprint"], item["title"], item.get("source", ""), job["id"])
            jobs.append(pipeline.run(job["id"]))
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
    if args.command == "demo":
        job = pipeline.create("Hermes content platform offline acceptance", ["demo"], {"audience": "Hermes operator"})
        pipeline.run(job["id"])
        pipeline.approve(job["id"], args.actor, "offline acceptance")
        return pipeline.publish(job["id"])
    raise ValueError(f"unsupported command: {args.command}")


def main(argv=None):
    try:
        result = execute(parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, PermissionError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
