import difflib
import json
from collections import Counter, defaultdict

from .admin_analysis import platform_llm_analysis
from .admin_store import AdminStore
from .formatters import format_for_platform
from .platform_catalog import all_platforms, platform_definition
from .readiness import inspect_delivery_readiness
from .store import Store


def _platform_rows(store, platform):
    with store.connect() as conn:
        latest = conn.execute(
            """
            SELECT j.id, j.topic, j.title, j.state, j.updated_at,
                   d.platform, d.status AS delivery_status, d.external_id, d.error
            FROM deliveries d
            JOIN jobs j ON j.id = d.job_id
            WHERE d.platform=?
            ORDER BY d.updated_at DESC, d.id DESC
            LIMIT 5
            """,
            (platform,),
        ).fetchall()
        delivery_counts = conn.execute(
            "SELECT status, COUNT(*) count FROM deliveries WHERE platform=? GROUP BY status",
            (platform,),
        ).fetchall()
        queue_counts = conn.execute(
            "SELECT state, COUNT(*) count FROM delivery_queue WHERE platform=? GROUP BY state",
            (platform,),
        ).fetchall()
        perf_rows = conn.execute(
            "SELECT platform, SUM(views) views, SUM(likes) likes, SUM(comments) comments, SUM(shares) shares FROM performance WHERE platform=? GROUP BY platform",
            (platform,),
        ).fetchall()
    return latest, delivery_counts, queue_counts, perf_rows


def _job_performance(store, job_id, platform):
    rows = store.performance(job_id)
    for row in rows:
        if row["platform"] == platform:
            return row
    return {"views": 0, "likes": 0, "comments": 0, "shares": 0}


def _latest_works(store, platform):
    latest, _, _, _ = _platform_rows(store, platform)
    rows = []
    for row in latest:
        perf = _job_performance(store, row["id"], platform)
        engagement = int(perf.get("likes", 0)) + int(perf.get("comments", 0)) + int(perf.get("shares", 0))
        rows.append(
            {
                "job_id": row["id"],
                "topic": row["topic"],
                "title": row["title"],
                "job_state": row["state"],
                "delivery_status": row["delivery_status"],
                "external_id": row["external_id"],
                "error": row["error"],
                "updated_at": row["updated_at"],
                "performance": perf,
                "engagement": engagement,
            }
        )
    return rows


def _platform_stats(store, platform):
    latest, delivery_counts, queue_counts, perf_rows = _platform_rows(store, platform)
    deliveries = {row["status"]: int(row["count"]) for row in delivery_counts}
    queue = {row["state"]: int(row["count"]) for row in queue_counts}
    perf = perf_rows[0] if perf_rows else {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    return {
        "delivery_counts": deliveries,
        "queue_counts": queue,
        "performance_totals": {
            "views": int(perf["views"] or 0),
            "likes": int(perf["likes"] or 0),
            "comments": int(perf["comments"] or 0),
            "shares": int(perf["shares"] or 0),
        },
        "latest_count": len(latest),
    }


def _platform_list(store, admin_store):
    static = {item["key"]: item for item in all_platforms()}
    keys = set(static)
    for row in admin_store.list_bindings():
        keys.add(row["platform"])
    for row in store.deliveries_all():
        keys.add(row["platform"])
    result = []
    for key in sorted(keys):
        meta = platform_definition(key)
        bindings = admin_store.list_bindings(key)
        stats = _platform_stats(store, key)
        result.append(
            {
                "key": key,
                "label": meta["label"],
                "group": meta["group"],
                "binding_count": len(bindings),
                "connected_count": sum(1 for item in bindings if item["status"] == "connected"),
                "enabled_count": sum(1 for item in bindings if item["enabled"]),
                "delivery_counts": stats["delivery_counts"],
                "queue_counts": stats["queue_counts"],
                "latest_count": stats["latest_count"],
                "supports": meta["supports"],
                "account_summaries": [
                    {
                        "display_name": binding["display_name"],
                        "track": binding.get("track", ""),
                        "current_status": binding.get("current_status", ""),
                        "status": binding.get("status", ""),
                    }
                    for binding in bindings[:3]
                ],
            }
        )
    return result


def build_overview(db_path):
    store = Store(db_path)
    admin_store = AdminStore(db_path)
    admin_store.init()
    platforms = _platform_list(store, admin_store)
    global_delivery = Counter()
    global_queue = Counter()
    performance = defaultdict(int)
    latest = []
    review_queue = []
    failures = []
    for item in platforms:
        for status, count in item["delivery_counts"].items():
            global_delivery[status] += int(count)
        for status, count in item["queue_counts"].items():
            global_queue[status] += int(count)
        platform_latest = _latest_works(store, item["key"])
        latest.extend(platform_latest)
        failures.extend(row for row in platform_latest if row["error"])
    for row in store.performance():
        performance["views"] += int(row["views"])
        performance["likes"] += int(row["likes"])
        performance["comments"] += int(row["comments"])
        performance["shares"] += int(row["shares"])
    for job in store.list_jobs(limit=20, state="review_required"):
        review_queue.append({"id": job["id"], "topic": job["topic"], "updated_at": job["updated_at"], "risk_level": job["risk_level"]})
    latest.sort(key=lambda row: row["updated_at"], reverse=True)
    failures.sort(key=lambda row: row["updated_at"], reverse=True)
    return {
        "platforms": platforms,
        "latest_works": latest[:5],
        "review_queue": review_queue[:10],
        "recent_failures": failures[:10],
        "charts": {
            "deliveries_by_status": [{"label": key, "value": value} for key, value in sorted(global_delivery.items())],
            "queue_by_state": [{"label": key, "value": value} for key, value in sorted(global_queue.items())],
            "bindings_by_platform": [{"label": item["label"], "value": item["binding_count"]} for item in platforms],
            "performance_totals": [
                {"label": "views", "value": performance["views"]},
                {"label": "likes", "value": performance["likes"]},
                {"label": "comments", "value": performance["comments"]},
                {"label": "shares", "value": performance["shares"]},
            ],
        },
    }


def build_platform_detail(db_path, platform, config=None):
    store = Store(db_path)
    admin_store = AdminStore(db_path)
    admin_store.init()
    meta = platform_definition(platform)
    bindings = admin_store.list_bindings(platform)
    stats = _platform_stats(store, platform)
    latest_works = _latest_works(store, platform)
    failures = [row for row in latest_works if row["error"]]
    readiness = inspect_delivery_readiness(config or {})
    track_counts = Counter(binding.get("track", "") for binding in bindings if binding.get("track"))
    status_counts = Counter(binding.get("current_status", "") for binding in bindings if binding.get("current_status"))
    historical = store.historical_performance([platform], platform)
    account_analysis = [
        {
            "id": binding["id"],
            "display_name": binding["display_name"],
            "account_key": binding["account_key"],
            "track": binding.get("track", ""),
            "current_status": binding.get("current_status", ""),
            "status": binding.get("status", ""),
            "auth_type": binding.get("auth_type", ""),
            "credentials_ref": binding.get("credentials_ref", ""),
            "notes": binding.get("notes", ""),
            "diagnosis": "已具备基础绑定条件" if binding.get("status") == "connected" else "建议先补全凭据与检测链路",
        }
        for binding in bindings
    ]
    llm_payload = {
        "platform": meta,
        "bindings": bindings,
        "stats": stats,
        "latest_works": latest_works,
        "historical": historical,
        "track_distribution": dict(track_counts),
        "current_status_distribution": dict(status_counts),
    }
    llm_analysis = platform_llm_analysis((config or {}).get("generator", {}), llm_payload)
    return {
        "platform": meta,
        "bindings": bindings,
        "binding_snapshot": {
            "track_distribution": dict(track_counts),
            "current_status_distribution": dict(status_counts),
        },
        "stats": stats,
        "historical": historical,
        "latest_works": latest_works,
        "recent_failures": failures,
        "account_analysis": account_analysis,
        "llm_analysis": llm_analysis,
        "binding_guide": meta["binding_steps"],
        "charts": {
            "deliveries_by_status": [{"label": key, "value": value} for key, value in sorted(stats["delivery_counts"].items())],
            "queue_by_state": [{"label": key, "value": value} for key, value in sorted(stats["queue_counts"].items())],
            "latest_views": [{"label": row["title"][:18] or row["topic"][:18], "value": int(row["performance"]["views"])} for row in latest_works],
            "latest_engagement": [{"label": row["title"][:18] or row["topic"][:18], "value": int(row["engagement"])} for row in latest_works],
            "tracks": [{"label": key, "value": value} for key, value in sorted(track_counts.items()) if key],
            "current_statuses": [{"label": key, "value": value} for key, value in sorted(status_counts.items()) if key],
        },
        "readiness": readiness,
    }


def build_task_center(db_path):
    store = Store(db_path)
    tasks = []
    for job in store.list_jobs(limit=100):
        deliveries = store.deliveries(job["id"])
        tasks.append(
            {
                "id": job["id"],
                "topic": job["topic"],
                "title": job["title"],
                "state": job["state"],
                "risk_level": job["risk_level"],
                "platforms": job["platforms"],
                "updated_at": job["updated_at"],
                "deliveries": deliveries,
            }
        )
    return {
        "tasks": tasks,
        "summary": dict(Counter(task["state"] for task in tasks)),
    }


def build_task_detail(db_path, job_id):
    store = Store(db_path)
    job = store.get_job(job_id)
    artifacts = store.artifacts(job_id)
    deliveries = store.deliveries(job_id)
    versions = store.draft_versions(job_id)
    platform_payloads = {}
    for platform in job["platforms"]:
        platform_payloads[platform] = format_for_platform(job, platform)
    geo_scores = store.geo_scores(job["id"])
    comparisons = []
    if len(versions) >= 2:
        old = versions[-2]["body"].splitlines()
        new = versions[-1]["body"].splitlines()
        comparisons = list(difflib.unified_diff(old, new, fromfile="previous", tofile="current", lineterm=""))
    return {
        "job": job,
        "artifacts": artifacts,
        "deliveries": deliveries,
        "draft_versions": versions,
        "platform_payloads": platform_payloads,
        "geo_scores": [{"score": g["score"], "when": g["created_at"], "details": json.loads(g.get("payload_json", "{}"))} for g in geo_scores],
        "comparisons": comparisons,
    }


def build_dashboard(db_path):
    store = Store(db_path)
    admin_store = AdminStore(db_path)
    admin_store.init()
    jobs = store.list_jobs(limit=500)
    total = len(jobs)
    published = sum(1 for j in jobs if j.get("state") == "published")
    review = sum(1 for j in jobs if j.get("state") == "review_required")
    blocked = sum(1 for j in jobs if j.get("state") == "blocked")
    failed = sum(1 for j in jobs if j.get("state") == "failed")
    geo_rows = store.geo_scores()
    geo_trend = []
    for g in geo_rows[-100:]:
        geo_trend.append({"score": g["score"], "when": g["created_at"][:10]})
    day_counts = {}
    for j in jobs:
        day = j.get("created_at", "")[:10]
        day_counts[day] = day_counts.get(day, 0) + 1
    heatmap = [{"day": k, "count": v} for k, v in sorted(day_counts.items())[-30:]]
    perf = [dict(p) for p in store._rows("SELECT * FROM performance", [])]
    failures = sum(1 for p in perf if p.get("views", 0) == 0)
    delivery_all = store.deliveries_all()
    fail_detail = {}
    for d in delivery_all:
        if d.get("status") == "failed":
            platform = d.get("platform", "unknown")
            fail_detail[platform] = fail_detail.get(platform, 0) + 1
    bindings = admin_store.list_bindings()
    return {
        "overview": {"total_jobs": total, "published": published, "review": review,
                      "blocked": blocked, "failed": failed,
                      "bindings": len(bindings), "failures": failures},
        "geo_trend": geo_trend,
        "content_heatmap": heatmap,
        "failures_by_platform": fail_detail,
     }
