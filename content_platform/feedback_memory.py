"""Feedback memory helpers used by post-publish review tasks."""

from __future__ import annotations

import uuid
from typing import Any


def build_feedback_memory(
    content_package_id: str,
    platform: str,
    insight: str,
    normalized_topic: str = "",
    source_type: str = "retrospective",
    priority: str = "medium",
) -> dict[str, Any]:
    return {
        "memory_id": f"fb_{uuid.uuid4().hex[:12]}",
        "content_package_id": content_package_id,
        "platform": platform,
        "source_type": source_type,
        "question_or_insight": insight,
        "normalized_topic": normalized_topic or insight[:40],
        "priority": priority,
    }
