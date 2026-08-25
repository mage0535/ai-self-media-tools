"""Truthful platform-hotspot identity, validation, and bounded scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any
from urllib.parse import urlparse
from pathlib import Path
import json


ASSOCIATION_MODES = {"auto_api", "auto_browser", "manual_handoff", "unsupported_or_unverified"}
ROOT = Path(__file__).resolve().parents[1]


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def validate_associated_hotspot(hotspot: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    hotspot = hotspot or {}
    failures: list[str] = []
    for field in ("platform", "hotspot_id", "title", "captured_at", "expires_at", "association_mode"):
        if not str(hotspot.get(field) or "").strip():
            failures.append(f"{field}_missing")
    mode = str(hotspot.get("association_mode") or "")
    if mode not in ASSOCIATION_MODES:
        failures.append("association_mode_invalid")
    if hotspot.get("canonical_url") and urlparse(str(hotspot["canonical_url"])).scheme not in {"http", "https"}:
        failures.append("canonical_url_invalid")
    captured = _parse_time(hotspot.get("captured_at"))
    expires = _parse_time(hotspot.get("expires_at"))
    if not captured or not expires:
        failures.append("hotspot_time_invalid")
    elif expires <= captured:
        failures.append("hotspot_expiry_invalid")
    reference = now or datetime.now(timezone.utc)
    if expires and expires <= reference:
        failures.append("hotspot_expired")
    native = hotspot.get("native_verified") is True
    if mode in {"auto_api", "auto_browser"} and not native:
        failures.append("auto_association_requires_native_verification")
    for field in ("heat_score", "lane_fit_score", "semantic_fit_score"):
        try:
            score = float(hotspot.get(field))
        except (TypeError, ValueError):
            failures.append(f"{field}_invalid")
            continue
        if not 0.0 <= score <= 1.0:
            failures.append(f"{field}_out_of_range")
    return {"passed": not failures, "failures": sorted(set(failures))}


def score_topic_with_hotspot(topic_scores: dict[str, Any] | None, hotspot: dict[str, Any] | None) -> dict[str, Any]:
    """Apply a bounded hotspot bonus only after topic quality remains eligible."""
    topic_scores = topic_scores or {}
    base = (
        float(topic_scores.get("platform_fit") or 0) * 0.35
        + float(topic_scores.get("utility") or 0) * 0.35
        + float(topic_scores.get("novelty") or 0) * 0.30
    )
    validation = validate_associated_hotspot(hotspot) if hotspot else {"passed": False, "failures": ["hotspot_missing"]}
    if not validation["passed"]:
        return {"score": round(min(1.0, base), 3), "base_score": round(base, 3), "hotspot_bonus": 0.0, "eligible": base >= 0.65, "hotspot_gate": validation}
    h = hotspot or {}
    hotspot_bonus = min(
        0.18,
        float(h.get("heat_score") or 0) * 0.06
        + float(h.get("lane_fit_score") or 0) * 0.06
        + float(h.get("semantic_fit_score") or 0) * 0.06,
    )
    score = min(1.0, base + hotspot_bonus)
    return {"score": round(score, 3), "base_score": round(base, 3), "hotspot_bonus": round(hotspot_bonus, 3), "eligible": base >= 0.65, "hotspot_gate": validation}


def load_hotspot_support_matrix(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path else ROOT / "config" / "hotspot_support_matrix.json"
    if not source.is_file():
        return {"version": "hotspot_support_matrix_v1", "default_mode": "unsupported_or_unverified", "platforms": {}}
    data = json.loads(source.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def hotspot_mode_for_platform(platform: str, matrix: dict[str, Any] | None = None) -> str:
    matrix = matrix or load_hotspot_support_matrix()
    record = (matrix.get("platforms") or {}).get(str(platform).casefold(), {})
    return str(record.get("association_mode") or matrix.get("default_mode") or "unsupported_or_unverified")


def build_associated_hotspot(candidate: dict[str, Any], *, platform: str, association_mode: str, now: datetime | None = None, validity_hours: float = 6, postcheck_state: str = "pending") -> dict[str, Any]:
    """Materialize one auditable, platform-bound hotspot record."""
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    target = str(platform or "").casefold().strip()
    candidate_platform = str(candidate.get("platform") or "").casefold().strip()
    if candidate_platform and candidate_platform != target:
        raise ValueError("associated hotspot platform mismatch")
    title = str(candidate.get("title") or "").strip()
    url = str(candidate.get("url") or candidate.get("canonical_url") or "").strip()
    hotspot_id = str(candidate.get("hotspot_id") or "").strip() or hashlib.sha256(f"{target}|{title}|{url}".encode("utf-8")).hexdigest()[:24]
    expires = candidate.get("expires_at") or (now + timedelta(hours=float(validity_hours))).isoformat()
    evidence_type = str(candidate.get("evidence_type") or "native").casefold()
    native = evidence_type == "native" and candidate.get("native_verified", True) is True
    expiry_dt = _parse_time(expires)
    validity = "valid" if expiry_dt and expiry_dt > now else "expired" if expiry_dt else "invalid"
    return {
        "version": "associated_hotspot_v2", "platform": target, "hotspot_id": hotspot_id, "title": title,
        "canonical_url": url, "source": str(candidate.get("source") or ""),
        "captured_at": str(candidate.get("captured_at") or now.isoformat()), "expires_at": str(expires), "validity": validity,
        "native_verified": native, "native_evidence": native, "evidence_type": evidence_type,
        "official_activity": evidence_type == "official_activity", "official_keyword": evidence_type == "official_keyword",
        "lane": str(candidate.get("lane") or "").strip(), "lane_fit_score": _bounded_score(candidate.get("lane_fit_score")),
        "semantic_fit_score": _bounded_score(candidate.get("semantic_fit_score")), "heat_score": _bounded_score(candidate.get("heat_score")),
        "association_mode": association_mode, "postcheck_state": str(postcheck_state or "pending"),
        "evidence_hash": str(candidate.get("evidence_hash") or hashlib.sha256(repr(sorted(candidate.items())).encode("utf-8")).hexdigest()),
    }


def persist_associated_hotspot(path: str | Path, hotspot: dict[str, Any]) -> dict[str, Any]:
    """Upsert hotspot evidence without losing prior platform records."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if target.is_file():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            rows = payload.get("hotspots", []) if isinstance(payload, dict) else payload
        except (OSError, json.JSONDecodeError):
            rows = []
    rows = [row for row in rows if isinstance(row, dict) and row.get("hotspot_id") != hotspot.get("hotspot_id")]
    rows.append(dict(hotspot))
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps({"version": "associated_hotspots_v2", "hotspots": rows}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return dict(hotspot)


def _bounded_score(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0
