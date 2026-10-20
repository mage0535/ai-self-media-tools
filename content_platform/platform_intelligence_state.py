"""Monotonic, fail-closed evidence eligibility for platform intelligence."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
STATES = (
    "S0_BLOCKED",
    "S1_SINGLE_SNAPSHOT",
    "S2_DUAL_SNAPSHOT_GROWTH",
    "S3_CONTENT_EVIDENCE",
    "S4_DEEP_COMPLETE",
    "S5_ADVISE",
    "S6_AUTO_LEARN",
)


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _permissions(state: str) -> dict[str, bool]:
    return {
        "allow_advice": state in {"S5_ADVISE", "S6_AUTO_LEARN"},
        "allow_viral_claims": False,
        "allow_automated_learning": state == "S6_AUTO_LEARN",
    }


def _valid_snapshot(snapshot: Any, platform: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(snapshot, dict):
        return None, ["snapshot_invalid"]
    reasons: list[str] = []
    identity = str(snapshot.get("content_id") or snapshot.get("canonical_url") or "").strip()
    observed = _aware(snapshot.get("observed_at"))
    metrics = snapshot.get("metrics")
    if str(snapshot.get("platform") or "").casefold() != platform:
        reasons.append("snapshot_platform_mismatch")
    if not identity:
        reasons.append("snapshot_identity_missing")
    if not observed:
        reasons.append("snapshot_timestamp_invalid")
    if not isinstance(metrics, dict) or not metrics:
        reasons.append("snapshot_metrics_missing")
    if not _hash(snapshot.get("raw_response_hash")):
        reasons.append("snapshot_raw_hash_invalid")
    if snapshot.get("native_verified") is not True:
        reasons.append("snapshot_not_native_verified")
    if reasons:
        return None, reasons
    return {**snapshot, "_identity": identity, "_observed": observed}, []


def _growth(snapshots: list[dict[str, Any]]) -> tuple[dict[str, Any], bool, list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in snapshots:
        grouped.setdefault(item["_identity"], []).append(item)
    result: dict[str, Any] = {}
    reasons: list[str] = []
    has_growth = False
    for identity, rows in grouped.items():
        rows.sort(key=lambda row: row["_observed"])
        if len(rows) < 2:
            continue
        baseline, current = rows[0], rows[-1]
        if baseline["_observed"] >= current["_observed"]:
            reasons.append("snapshot_order_invalid")
            continue
        metrics: dict[str, Any] = {}
        common = set(baseline["metrics"]) & set(current["metrics"])
        for metric in sorted(common):
            try:
                before, after = float(baseline["metrics"][metric]), float(current["metrics"][metric])
            except (TypeError, ValueError):
                continue
            if before < 0 or after < 0:
                continue
            delta = after - before
            metrics[metric] = {
                "baseline": int(before) if before.is_integer() else before,
                "current": int(after) if after.is_integer() else after,
                "delta": int(delta) if delta.is_integer() else delta,
                "rate": round(delta / max(before, 1.0), 6),
            }
        if metrics:
            result[identity] = {"baseline_observed_at": baseline["observed_at"], "current_observed_at": current["observed_at"], "metrics": metrics}
            has_growth = True
    if not has_growth:
        reasons.append("comparable_dual_snapshot_missing")
    return result, has_growth, reasons


def _content_ready(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("body_verified") is not True:
        return False
    refs = value.get("evidence_refs")
    return isinstance(refs, list) and len(refs) >= 2 and all(
        isinstance(ref, dict) and _hash(ref.get("sha256")) and ref.get("source_url") for ref in refs
    )


def _breakdown_ready(value: Any, platform: str, lane: str, now: datetime) -> bool:
    if not isinstance(value, dict):
        return False
    expires = _aware((value.get("cache") or {}).get("expires_at"))
    return bool(
        value.get("status") == "ready"
        and (value.get("validation") or {}).get("passed") is True
        and str(value.get("platform") or "").casefold() == platform
        and str(value.get("lane") or "") == lane
        and int((value.get("summary") or {}).get("accepted_samples") or 0) > 0
        and expires and now < expires
    )


def _recommendation_ready(value: Any, identities: set[str]) -> bool:
    if not isinstance(value, dict):
        return False
    refs, hashes = value.get("reference_ids"), value.get("evidence_hashes")
    return isinstance(refs, list) and bool(set(map(str, refs)) & identities) and isinstance(hashes, list) and bool(hashes) and all(_hash(item) for item in hashes)


def evaluate_platform_intelligence(
    *, platform: str, lane: str, snapshots: list[dict[str, Any]] | None = None,
    content_evidence: dict[str, Any] | None = None, breakdown: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None, learning_evaluation: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the highest earned state; every omitted predecessor remains blocked."""
    canonical_platform = str(platform or "").casefold().strip()
    current = now.astimezone(timezone.utc) if now and now.tzinfo else datetime.now(timezone.utc)
    reasons: list[str] = []
    valid: list[dict[str, Any]] = []
    for snapshot in snapshots or []:
        normalized, failures = _valid_snapshot(snapshot, canonical_platform)
        reasons.extend(failures)
        if normalized:
            valid.append(normalized)
    if not valid:
        state = "S0_BLOCKED"
        reasons.append("verified_snapshot_missing")
        return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": {}, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}

    state = "S1_SINGLE_SNAPSHOT"
    growth, dual_ready, growth_reasons = _growth(valid)
    reasons.extend(growth_reasons)
    if not dual_ready:
        return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": growth, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}

    state = "S2_DUAL_SNAPSHOT_GROWTH"
    if not _content_ready(content_evidence):
        reasons.append("content_evidence_incomplete")
        return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": growth, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}

    state = "S3_CONTENT_EVIDENCE"
    if not _breakdown_ready(breakdown, canonical_platform, lane, current):
        reasons.append("deep_breakdown_incomplete_or_stale")
        return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": growth, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}

    state = "S4_DEEP_COMPLETE"
    identities = {item["_identity"] for item in valid}
    if not _recommendation_ready(recommendation, identities):
        reasons.append("recommendation_evidence_binding_missing")
        return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": growth, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}

    state = "S5_ADVISE"
    # Public intelligence is generation/planning evidence only.  A caller-owned
    # dictionary can never grant a production learning permission; the only
    # executable decision source is OwnedLearningStore.strategy_health().
    if learning_evaluation is not None:
        reasons.append("public_learning_evaluation_not_authoritative")
    return {"version": "platform_intelligence_state_v1", "platform": canonical_platform, "lane": lane, "state": state, "growth": growth, "blocking_reason_codes": list(dict.fromkeys(reasons)), "permissions": _permissions(state)}


def evaluate_platform_history(
    *, platform: str, lane: str, history_index: str | Any, now: datetime | None = None,
) -> dict[str, Any]:
    """Verify immutable archives, aggregate one platform's snapshots, then evaluate it."""
    import hashlib
    import json
    from pathlib import Path

    canonical_platform = str(platform or "").casefold().strip()
    verified_archives = 0
    snapshots: list[dict[str, Any]] = []
    reasons: list[str] = []
    try:
        lines = Path(history_index).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
        reasons.append("history_index_unavailable")
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            path = Path(str(entry.get("path") or ""))
            raw = path.read_bytes()
            if not _hash(entry.get("sha256")) or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                reasons.append("archive_hash_mismatch")
                continue
            bundle = json.loads(raw)
            if not isinstance(bundle, dict):
                raise ValueError("bundle_not_object")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            reasons.append("archive_unreadable_or_invalid")
            continue
        verified_archives += 1
        snapshots.extend(
            item for item in bundle.get("items") or []
            if isinstance(item, dict) and str(item.get("platform") or "").casefold() == canonical_platform
        )
    result = evaluate_platform_intelligence(
        platform=canonical_platform, lane=lane, snapshots=snapshots, now=now,
    )
    result["history"] = {"verified_archives": verified_archives, "snapshot_count": len(snapshots)}
    if reasons:
        result["blocking_reason_codes"] = list(dict.fromkeys(result["blocking_reason_codes"] + reasons))
    return result

