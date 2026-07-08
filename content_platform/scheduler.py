"""
Scheduler — cron-expression-driven content scheduling.
Integrates with admin console for calendar view and scheduled publishing.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta


def _cron_next(cron_expr, from_dt=None):
    cron_expr = cron_expr.strip()
    dt = from_dt or datetime.now()
    if cron_expr == "@daily":
        return dt.replace(hour=8, minute=0, second=0) + timedelta(days=1 if dt.hour >= 8 else 0)
    if cron_expr == "@weekly":
        days_ahead = 6 - dt.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return dt.replace(hour=8, minute=0, second=0) + timedelta(days=days_ahead)
    if cron_expr == "@hourly":
        return dt.replace(minute=0, second=0) + timedelta(hours=1)
    return dt + timedelta(hours=1)


def schedule_job(store, topic, platforms, brief=None, profile="default",
                 cron="@daily", enabled=True, label=""):
    next_run = _cron_next(cron)
    store.save_schedule({
        "topic": topic, "platforms": json.dumps(platforms),
        "brief": json.dumps(brief or {}), "profile": profile,
        "cron": cron, "enabled": int(bool(enabled)),
        "label": label or topic, "next_run": next_run.isoformat(),
        "last_run": "", "created_at": datetime.now().isoformat(),
    })
    return {"ok": True, "next_run": next_run.isoformat(), "label": label or topic}


def list_schedules(store):
    rows = store.list_schedules()
    return [{"id": r["id"], "topic": r["topic"], "platforms": json.loads(r.get("platforms", "[]")),
             "cron": r["cron"], "enabled": bool(r["enabled"]), "label": r.get("label", r["topic"]),
             "next_run": r["next_run"], "last_run": r["last_run"]} for r in rows]


def toggle_schedule(store, schedule_id, enabled):
    store.update_schedule(schedule_id, enabled=int(bool(enabled)))
    return {"ok": True, "enabled": enabled}


def process_due_schedules(store, pipeline):
    rows = store.list_schedules()
    now = datetime.now().isoformat()
    executed = 0
    for row in rows:
        if not int(row.get("enabled", 1)):
            continue
        next_run = row.get("next_run", "")
        if next_run and next_run > now:
            continue
        job = pipeline.create(
            row["topic"],
            json.loads(row.get("platforms", "[]")),
            json.loads(row.get("brief", "{}")),
            row.get("profile", "default"),
        )
        store.update_schedule(row["id"], enabled=row["enabled"],
                              last_run=now, next_run=_cron_next(row["cron"]).isoformat())
        executed += 1
    return {"executed": executed}
