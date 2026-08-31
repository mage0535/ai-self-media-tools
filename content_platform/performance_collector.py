"""Review task registration and unavailable-safe performance records."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone


DEFAULT_REVIEW_POINTS = [
    {"after_publish_hours": 1, "purpose": "publish status and platform error check"},
    {"after_publish_hours": 24, "purpose": "early performance review"},
    {"after_publish_hours": 72, "purpose": "mid-term performance review"},
    {"after_publish_hours": 168, "purpose": "long-tail performance review"},
]


def register_review_tasks(store: Any, content_package_id: str, platform: str, job_id: str = "", schedule: list[dict] | None = None):
    return store.create_review_tasks(content_package_id, platform, schedule or DEFAULT_REVIEW_POINTS, job_id=job_id)


def unavailable_performance(platform: str, reason: str, review_point_hours: int = 0) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "platform": platform,
        "review_point_hours": int(review_point_hours),
        "metrics": {},
        "unavailable_reason": reason,
    }


def collect_due_metric_windows(ledger: Any, collector: Any, *, now: datetime | None = None, max_attempts: int = 3, retry_after_seconds: int = 300) -> dict[str, Any]:
    """Collect only due windows and preserve unavailable data as insufficient."""
    checked_at = now or datetime.now(timezone.utc)
    identities = {row["id"]: row for row in ledger.identities()}
    report = {"status": "ok", "collected": 0, "insufficient": 0, "retry_pending": 0, "invalidated": 0, "leased": 0}
    for window in ledger.due_windows():
        due_at = datetime.fromisoformat(str(window["due_at"]).replace("Z", "+00:00"))
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if due_at > checked_at:
            continue
        if not ledger.metric_retry_due(window["id"], checked_at):
            report["retry_pending"] += 1
            continue
        identity = identities.get(window["identity_id"])
        if not identity:
            ledger.invalidate_window(window["id"], "publication_identity_missing")
            report["invalidated"] += 1
            continue
        try:
            attempt = ledger.begin_metric_collection(window["id"], now=checked_at)
        except ValueError:
            report["leased"] += 1
            continue
        try:
            result = collector(dict(identity)) or {}
        except Exception as exc:
            result = {"status": "unavailable", "source": "collector", "confidence": "unknown", "reason": str(exc)[:300]}
        metrics = result.get("metrics") or result.get("account_metrics") or {}
        status = str(result.get("status") or "unavailable").casefold()
        usable = status in {"ok", "success", "collected"} and any(value is not None for value in metrics.values())
        if not usable and ledger.metric_attempt_count(window["id"]) < max(1, int(max_attempts)):
            reason = str(result.get("reason") or "metric collector returned insufficient data")
            ledger.finish_metric_collection(
                window["id"], attempt["attempt_id"], "retry_pending", reason,
                now=checked_at, retry_after_seconds=retry_after_seconds,
            )
            report["retry_pending"] += 1
            continue
        observation = ledger.record_metrics(
            window["id"],
            metrics if usable else {},
            source=str(result.get("source") or result.get("metric_source") or "collector"),
            confidence=str(result.get("confidence") or result.get("metric_confidence") or "unknown"),
            platform=str(identity.get("platform") or ""),
            internal_account_alias=str(identity.get("internal_account_alias") or identity.get("account_id") or ""),
            platform_content_id=str(identity.get("platform_content_id") or ""),
            observed_at=checked_at,
        )
        ledger.finish_metric_collection(window["id"], attempt["attempt_id"], observation["state"], now=checked_at)
        report["collected" if observation["state"] == "collected" else "insufficient"] += 1
    return report
