"""Shadow engagement signal for topic ranking (MED3 P1, 2026-10-30).

Feed points measure reach; this measures how strongly viewers reacted to the
source work.  Platform weights for saves/comments/shares are unverified
third-party claims, so every interaction counts once and the value is only
recorded next to the topic decision.  It does not change the ranking until it
has been compared with our own published-work metrics.
"""

from __future__ import annotations

from typing import Any

INTERACTION_KEYS = ("likes", "comments", "favorites", "shares", "coins")


def engagement_quality(item: dict[str, Any]) -> float | None:
    """Interactions per view of the source work, or None when the feed has no counts."""
    metrics = item.get("metrics") if isinstance(item, dict) else None
    if not isinstance(metrics, dict):
        return None
    try:
        views = float(metrics.get("views") or 0)
        counts = [float(metrics[key]) for key in INTERACTION_KEYS if metrics.get(key) is not None]
    except (TypeError, ValueError):
        return None
    if views <= 0 or not counts:
        return None
    return round(sum(max(0.0, value) for value in counts) / views, 4)
