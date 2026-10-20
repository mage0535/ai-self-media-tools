"""Fail-closed platform intelligence capability contracts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES_PATH = ROOT / "config" / "platform_intelligence_capabilities_v1.json"
CAPABILITY_NAMES = (
    "topic_discovery",
    "work_level_metrics",
    "deep_content_analysis",
    "automated_learning",
)


def load_platform_intelligence_status(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the canonical AI-platform registry; fail closed on drift."""
    from .real_world_ai_policy import load_real_world_ai_positioning

    source = Path(path) if path else CAPABILITIES_PATH
    raw = json.loads(source.read_text(encoding="utf-8"))
    policy = load_real_world_ai_positioning()
    if raw.get("policy_profile") != policy.get("policy_profile"):
        raise ValueError("platform intelligence policy profile mismatch")
    if raw.get("policy_revision") != policy.get("policy_revision"):
        raise ValueError("platform intelligence policy revision mismatch")
    platforms = raw.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError("platform intelligence registry has no platforms")
    if set(platforms) != set(policy.get("platforms") or []):
        raise ValueError("platform intelligence registry platform set mismatch")
    for name, entry in platforms.items():
        capabilities = entry.get("capabilities") if isinstance(entry, dict) else None
        if not isinstance(capabilities, dict) or set(capabilities) != set(CAPABILITY_NAMES):
            raise ValueError(f"invalid capability set for {name}")
        if capabilities["automated_learning"].get("enabled") is not False:
            raise ValueError(f"automated learning must remain fail-closed for {name}")
    return raw


def platform_intelligence_generation_constraints(platform: str, *, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Give generators safe evidence boundaries; unknown platforms cannot use signals."""
    registry = registry or load_platform_intelligence_status()
    entry = (registry.get("platforms") or {}).get(str(platform or "").casefold())
    if not isinstance(entry, dict):
        return {
            "version": "platform_intelligence_generation_constraints_v1",
            "platform": str(platform or ""), "generation_only": True,
            "allow_topic_signals": False, "allow_viral_claims": False,
            "allow_visual_cta_pattern_claims": False, "allow_automated_learning": False,
            "required_disclaimers": ["platform_intelligence_status_unknown"],
        }
    capabilities = entry["capabilities"]
    topic = capabilities["topic_discovery"]
    deep = capabilities["deep_content_analysis"]
    work = capabilities["work_level_metrics"]
    reasons = []
    for capability in (topic, work, deep, capabilities["automated_learning"]):
        if not capability.get("enabled"):
            reasons.append(str(capability.get("reason") or capability.get("mode") or "capability_unavailable"))
    if not deep.get("enabled"):
        reasons.append("body_or_native_page_verification_missing")
    return {
        "version": "platform_intelligence_generation_constraints_v1",
        "platform": str(platform).casefold(), "generation_only": True,
        "allow_topic_signals": bool(topic.get("enabled")), "allow_viral_claims": False,
        "allow_visual_cta_pattern_claims": bool(deep.get("enabled")), "allow_automated_learning": False,
        "required_disclaimers": list(dict.fromkeys(reasons)), "capabilities": capabilities,
    }


def load_platform_intelligence_runtime_constraints(
    platform: str, *, path: str | Path | None = None
) -> dict[str, Any]:
    """Load current source freshness; unavailable/stale evidence cannot enter discovery context."""
    source = Path(path) if path else Path(__import__("os").environ.get("CONTENT_PLATFORM_DATA_DIR") or ROOT / "data") / "intel" / "platform_intelligence_runtime_latest.json"
    base = platform_intelligence_generation_constraints(platform)
    try:
        snapshot = json.loads(source.read_text(encoding="utf-8"))
        runtime = ((snapshot.get("platforms") or {}).get(str(platform).casefold()) or {}).get("runtime_collection") or {}
        registry = load_platform_intelligence_status()
        if (
            snapshot.get("policy_profile") != registry.get("policy_profile")
            or snapshot.get("policy_revision") != registry.get("policy_revision")
            or snapshot.get("source_bundle_version") != "platform_hot_evidence_bundle_v1"
        ):
            runtime = {"state": "version_mismatch", "reason_codes": ["runtime_status_policy_or_bundle_version_mismatch"]}
    except (OSError, json.JSONDecodeError):
        runtime = {"state": "missing_snapshot", "reason_codes": ["runtime_status_snapshot_missing"]}
    state = str(runtime.get("state") or "missing_snapshot")
    if state != "fresh_usable":
        base["allow_topic_signals"] = False
        base["required_disclaimers"] = list(dict.fromkeys(base["required_disclaimers"] + list(runtime.get("reason_codes") or []) + [f"platform_hot_evidence_{state}"]))
    base["runtime_collection"] = {
        "state": state,
        "usable_for_generation_context": bool(runtime.get("usable_for_generation_context")) and state == "fresh_usable",
        "observed_at": runtime.get("observed_at"),
        "age_seconds": runtime.get("age_seconds"),
        "reason_codes": list(runtime.get("reason_codes") or []),
    }
    return base


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def build_platform_intelligence_runtime_snapshot(
    *, registry: dict[str, Any] | None = None, bundle: dict[str, Any] | None = None,
    now: datetime | None = None, max_age_seconds: int = 86400,
) -> dict[str, Any]:
    """Combine static limits with a current bundle; stale/invalid evidence never becomes usable."""
    registry = registry or load_platform_intelligence_status()
    bundle = bundle if isinstance(bundle, dict) else {}
    now = now.astimezone(timezone.utc) if now and now.tzinfo else datetime.now(timezone.utc)
    aliases = {"douyin": "douyin_ai"}
    sources_by_platform: dict[str, list[dict[str, Any]]] = {}
    for source in bundle.get("sources") or []:
        if not isinstance(source, dict):
            continue
        platform = aliases.get(str(source.get("platform") or "").casefold(), str(source.get("platform") or "").casefold())
        if platform:
            sources_by_platform.setdefault(platform, []).append({
                "source": source.get("source"), "kind": source.get("kind"),
                "status": source.get("status"), "count": source.get("count"),
            })
    item_count: dict[str, int] = {}
    for item in bundle.get("items") or []:
        if isinstance(item, dict):
            platform = aliases.get(str(item.get("platform") or "").casefold(), str(item.get("platform") or "").casefold())
            if platform:
                item_count[platform] = item_count.get(platform, 0) + 1
    observed = _parse_aware_timestamp(bundle.get("observed_at"))
    identity_matches = (
        bundle.get("version") == "platform_hot_evidence_bundle_v1"
        and bundle.get("policy_profile") == registry.get("policy_profile")
        and bundle.get("policy_revision") == registry.get("policy_revision")
    )
    platforms: dict[str, Any] = {}
    for platform, entry in (registry.get("platforms") or {}).items():
        sources = sources_by_platform.get(platform, [])
        count = item_count.get(platform, 0)
        statuses = [str(source.get("status") or "unknown") for source in sources]
        reason_codes: list[str] = []
        age_seconds: int | None = None
        if not identity_matches:
            state = "version_mismatch"
            reason_codes.append("policy_profile_revision_or_bundle_version_mismatch")
        elif not sources:
            state = "not_configured"
            reason_codes.append("no_configured_collector")
        elif not all(status == "ok" for status in statuses):
            state = "collection_failed"
            reason_codes.append("source_collection_not_ok")
        elif observed is None:
            state = "invalid_snapshot"
            reason_codes.append("observed_at_missing_or_timezone_naive")
        else:
            age_seconds = int((now - observed).total_seconds())
            if age_seconds < 0:
                state = "future_timestamp"
                reason_codes.append("observed_at_in_future")
            elif age_seconds > max_age_seconds:
                state = "stale"
                reason_codes.append("snapshot_exceeds_max_age")
            elif count == 0:
                state = "fresh_empty"
                reason_codes.append("no_lane_matched_items")
            else:
                state = "fresh_usable"
        usable = state == "fresh_usable" and bool(entry["capabilities"]["topic_discovery"].get("enabled"))
        platforms[platform] = {
            "capabilities": entry["capabilities"],
            "runtime_collection": {
                "state": state, "usable_for_generation_context": usable,
                "source_count": len(sources), "accepted_item_count": count, "sources": sources,
                "observed_at": observed.isoformat().replace("+00:00", "Z") if observed else None,
                "age_seconds": age_seconds, "reason_codes": reason_codes,
            },
            "generation_constraints": platform_intelligence_generation_constraints(platform, registry=registry),
        }
    return {
        "version": "platform_intelligence_runtime_snapshot_v2",
        "generated_at": now.isoformat().replace("+00:00", "Z"), "max_age_seconds": max_age_seconds,
        "policy_profile": registry.get("policy_profile"),
        "policy_revision": registry.get("policy_revision"),
        "source_bundle_version": bundle.get("version"),
        "platforms": platforms,
    }
