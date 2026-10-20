"""Fail-closed fusion of audited DailyHot and research-only evidence."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


_BUNDLE_VERSION = "platform_hot_evidence_bundle_v1"
_DAILYHOT_SIGNALS = {"topic_signal", "ranked_content_candidate"}
_RESEARCH_SIGNAL = "research_content_snapshot"
_WINDOW = timedelta(hours=6)


def _normalized_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _observed_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_row(raw: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(raw, dict):
        return None, "row_not_object"
    if raw.get("fusion_eligible") is False:
        return None, "explicitly_fusion_ineligible"
    platform = str(raw.get("platform") or "").casefold().strip()
    title = str(raw.get("title") or "").strip()
    normalized = _normalized_title(title)
    observed = _observed_at(raw.get("observed_at"))
    source = str(raw.get("source") or "").casefold().strip()
    collector = str(raw.get("collector") or "").casefold().strip()
    signal_type = str(raw.get("signal_type") or "").casefold().strip()
    raw_hash = str(raw.get("raw_response_hash") or "").strip()
    if not all((platform, title, normalized, observed, source, collector, signal_type, raw_hash)):
        return None, "required_field_missing"
    is_dailyhot = source == "dailyhot_api" and collector == "dailyhot_api" and signal_type in _DAILYHOT_SIGNALS
    is_research = (
        source == "mediacrawler_research_import"
        and collector == "mediacrawler_research_import"
        and signal_type == _RESEARCH_SIGNAL
        and raw.get("research_only") is True
        and raw.get("native_verified") is False
        and raw.get("auto_selection_eligible") is False
    )
    if not is_dailyhot and not is_research:
        return None, "unsupported_or_policy_violation"
    if raw.get("native_verified") is not False or raw.get("auto_selection_eligible") is not False:
        return None, "source_flag_escalation"
    return {
        "platform": platform,
        "title": title[:200],
        "normalized_title": normalized,
        "observed_at": observed,
        "source": source,
        "collector": collector,
        "signal_type": signal_type,
        "raw_response_hash": raw_hash,
        "content_id": str(raw.get("content_id") or "")[:120],
        "canonical_url": str(raw.get("canonical_url") or "")[:500],
        "rank": raw.get("rank") or 0,
        "research_only": is_research,
        "kind": "research" if is_research else "dailyhot",
    }, ""


def fuse_platform_hot_evidence(bundle: dict[str, Any], *, max_items_per_source: int = 20, max_clusters_per_platform: int = 20) -> dict[str, Any]:
    """Return deterministic, generation-only evidence clusters without rank mutation."""
    if not isinstance(bundle, dict) or bundle.get("version") != _BUNDLE_VERSION or not isinstance(bundle.get("items"), list):
        return {"version": "platform_hot_fusion_v1", "status": "invalid", "auto_selection_eligible": False, "platforms": {}, "rejected_count": 0}
    valid: list[dict[str, Any]] = []
    rejected = 0
    source_counts: dict[tuple[str, str], int] = defaultdict(int)
    for raw in bundle["items"]:
        row, error = _safe_row(raw)
        if row is None:
            rejected += 1
            continue
        key = (row["platform"], row["kind"])
        if source_counts[key] >= max(1, int(max_items_per_source)):
            continue
        source_counts[key] += 1
        valid.append(row)
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in valid:
        grouped[row["platform"]][row["normalized_title"]].append(row)
    platforms: dict[str, Any] = {}
    corroborated = 0
    for platform in sorted(grouped):
        clusters = []
        for title_key in sorted(grouped[platform]):
            rows = sorted(grouped[platform][title_key], key=lambda row: (row["observed_at"], row["raw_response_hash"]))
            dailyhot = [row for row in rows if row["kind"] == "dailyhot"]
            research = [row for row in rows if row["kind"] == "research"]
            aligned = bool(dailyhot and research) and (max(row["observed_at"] for row in rows) - min(row["observed_at"] for row in rows) <= _WINDOW)
            dailyhot_identities = {row["content_id"] or row["canonical_url"] for row in dailyhot if row["content_id"] or row["canonical_url"]}
            research_identities = {row["content_id"] or row["canonical_url"] for row in research if row["content_id"] or row["canonical_url"]}
            same_content = bool(dailyhot_identities.intersection(research_identities))
            if aligned and same_content:
                status = "corroborated"
                corroborated += 1
            elif aligned:
                status = "topic_aligned"
            else:
                status = "single_source"
            identity = f"{platform}\0{title_key}\0" + "\0".join(row["raw_response_hash"] for row in rows)
            clusters.append({
                "cluster_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                "title": rows[0]["title"],
                "normalized_title": title_key,
                "status": status,
                "dailyhot_refs": [{"raw_response_hash": row["raw_response_hash"], "content_id": row["content_id"], "canonical_url": row["canonical_url"], "rank": row["rank"], "signal_type": row["signal_type"]} for row in dailyhot],
                "research_refs": [{"raw_response_hash": row["raw_response_hash"], "content_id": row["content_id"], "canonical_url": row["canonical_url"], "signal_type": row["signal_type"]} for row in research],
                "window_start": min(row["observed_at"] for row in rows).isoformat(),
                "window_end": max(row["observed_at"] for row in rows).isoformat(),
                "research_only": bool(research),
                "native_verified": False,
                "auto_selection_eligible": False,
                "generation_only": True,
            })
        truncated = len(clusters) > max(1, int(max_clusters_per_platform))
        clusters = clusters[:max(1, int(max_clusters_per_platform))]
        platforms[platform] = {
            "status": "fused" if any(cluster["status"] == "corroborated" for cluster in clusters) else "partial",
            "dailyhot_count": sum(1 for row in valid if row["platform"] == platform and row["kind"] == "dailyhot"),
            "research_count": sum(1 for row in valid if row["platform"] == platform and row["kind"] == "research"),
            "clusters": clusters,
            "truncated": truncated,
        }
    return {
        "version": "platform_hot_fusion_v1",
        "status": "fused" if corroborated else ("partial" if platforms else "insufficient"),
        "auto_selection_eligible": False,
        "platforms": platforms,
        "rejected_count": rejected,
    }
