"""Review task registration and unavailable-safe performance records."""

from __future__ import annotations

from typing import Any


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
