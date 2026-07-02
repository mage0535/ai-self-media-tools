import os
import time
from datetime import datetime
from pathlib import Path

from .publishers import AyrshareQuotaStore


def _timestamp(value):
    if not value:
        return 0
    return datetime.fromisoformat(value).timestamp()


def _metric_label(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def render_metrics(store):
    lines = ["# HELP hermes_content_jobs Content jobs by state", "# TYPE hermes_content_jobs gauge"]
    with store.connect() as conn:
        for row in conn.execute("SELECT state,COUNT(*) count FROM jobs GROUP BY state ORDER BY state"):
            lines.append(f'hermes_content_jobs{{state="{row["state"]}"}} {row["count"]}')
        lines.extend(["# HELP hermes_content_views_total Recorded content views", "# TYPE hermes_content_views_total counter"])
        for row in conn.execute("SELECT platform,SUM(views) views FROM performance GROUP BY platform ORDER BY platform"):
            lines.append(f'hermes_content_views_total{{platform="{row["platform"]}"}} {row["views"] or 0}')
        lines.extend(["# HELP hermes_content_delivery_failures Delivery failures", "# TYPE hermes_content_delivery_failures gauge"])
        for row in conn.execute("SELECT platform,COUNT(*) count FROM deliveries WHERE status IN ('failed','blocked') GROUP BY platform"):
            lines.append(f'hermes_content_delivery_failures{{platform="{row["platform"]}"}} {row["count"]}')
        lines.extend(["# HELP hermes_content_deliveries Platform deliveries by status", "# TYPE hermes_content_deliveries gauge"])
        for row in conn.execute("SELECT platform,status,COUNT(*) count FROM deliveries GROUP BY platform,status"):
            lines.append(f'hermes_content_deliveries{{platform="{row["platform"]}",status="{row["status"]}"}} {row["count"]}')
        artifact_bytes = 0
        for row in conn.execute("SELECT path FROM artifacts"):
            try:
                artifact_bytes += os.path.getsize(row["path"])
            except OSError:
                pass
        lines.extend(
            [
                "# HELP hermes_content_artifact_bytes Total bytes of registered artifacts",
                "# TYPE hermes_content_artifact_bytes gauge",
                f"hermes_content_artifact_bytes {artifact_bytes}",
            ]
        )
        oldest = conn.execute("SELECT MIN(updated_at) value FROM jobs WHERE state='review_required'").fetchone()["value"]
        age = max(0, int(time.time() - _timestamp(oldest))) if oldest else 0
        lines.extend(
            [
                "# HELP hermes_content_oldest_review_age_seconds Age of the oldest pending review",
                "# TYPE hermes_content_oldest_review_age_seconds gauge",
                f"hermes_content_oldest_review_age_seconds {age}",
            ]
        )
        latest = conn.execute("SELECT MAX(created_at) value FROM events").fetchone()["value"]
        lines.extend(
            [
                "# HELP hermes_content_last_event_timestamp_seconds Timestamp of the latest workflow event",
                "# TYPE hermes_content_last_event_timestamp_seconds gauge",
                f"hermes_content_last_event_timestamp_seconds {int(_timestamp(latest))}",
            ]
        )
    quota_rows = AyrshareQuotaStore(Path(store.path).parent / "ayrshare_quota.db").usage_rows()
    if quota_rows:
        lines.extend(
            [
                "# HELP hermes_content_ayrshare_quota_used Ayrshare monthly quota used",
                "# TYPE hermes_content_ayrshare_quota_used gauge",
            ]
        )
        for row in quota_rows:
            labels = f'account="{_metric_label(row["account"])}",platform="{_metric_label(row["platform"])}",month="{_metric_label(row["month"])}"'
            lines.append(f'hermes_content_ayrshare_quota_used{{{labels}}} {int(row["used"])}')
        lines.extend(
            [
                "# HELP hermes_content_ayrshare_quota_remaining Ayrshare monthly quota remaining",
                "# TYPE hermes_content_ayrshare_quota_remaining gauge",
            ]
        )
        for row in quota_rows:
            labels = f'account="{_metric_label(row["account"])}",platform="{_metric_label(row["platform"])}",month="{_metric_label(row["month"])}"'
            remaining = max(0, int(row["monthly_limit"]) - int(row["used"]))
            lines.append(f"hermes_content_ayrshare_quota_remaining{{{labels}}} {remaining}")
    return "\n".join(lines) + "\n"
