"""Evidence-preserving breakdowns for credential-free public work snapshots.

This is intentionally separate from ``viral_breakdown``: public metadata can
support topic planning, but it cannot manufacture script, visual, CTA, or
engagement conclusions when the source did not expose them.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
OBSERVED_FIELDS = (
    "canonical_url", "content_id", "title", "author", "published_at",
    "duration_seconds", "metrics", "observed_at", "source",
    "collector", "raw_response_hash",
)
DEEP_BREAKDOWN_FIELDS = (
    "copy_or_script", "content_structure", "visual_evidence",
    "cta", "voiceover", "motion_combination", "transition_combination",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def build_public_work_breakdowns(bundle: dict[str, Any], *, generated_at: datetime | None = None) -> dict[str, Any]:
    """Materialize only observed evidence; missing dimensions remain missing."""
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for raw in bundle.get("items") or []:
        item = _as_dict(raw)
        platform = str(item.get("platform") or "").strip().casefold()
        if not platform or not item.get("canonical_url") or not item.get("content_id"):
            continue
        observed = {key: item[key] for key in OBSERVED_FIELDS if item.get(key) is not None}
        missing = [key for key in DEEP_BREAKDOWN_FIELDS if not item.get(key)]
        rows.append({
            "platform": platform,
            "content_id": str(item["content_id"]),
            "canonical_url": str(item["canonical_url"]),
            "evidence_level": str(item.get("evidence_level") or "public_work_snapshot"),
            "native_verified": bool(item.get("native_verified")),
            "generation_only": True,
            "decision": "review_required",
            "observed_evidence": observed,
            "observed_title": str(item.get("title") or ""),
            "observed_metrics": _as_dict(item.get("metrics")),
            "deep_breakdown_status": "partial" if missing else "complete_evidence_pending_review",
            "missing_evidence": missing,
            "prohibited_claims": [
                "viral_conclusion", "causal_growth_rule", "unobserved_script_or_visual_analysis",
            ],
        })
    counts = Counter(row["platform"] for row in rows)
    return {
        "version": "public_work_breakdown_v1",
        "generated_at": generated.isoformat(),
        "source_bundle_observed_at": bundle.get("observed_at"),
        "status": "review_required" if rows else "blocked",
        "generation_only": True,
        "auto_selection_eligible": False,
        "summary": {"sample_count": len(rows), "platform_counts": dict(sorted(counts.items()))},
        "samples": rows,
    }
