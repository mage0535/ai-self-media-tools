"""Fail-closed provenance for public listening and owned analytics inputs."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
SENSITIVE_PARTS = ("cookie", "token", "password", "secret", "authorization", "session", "credential", "proxy")
SOURCE_CLASSES = frozenset({
    "public_web_observation", "official_authorized", "licensed_vendor", "derived_model_signal",
})
_PURPOSES = frozenset({"topic_planning", "owned_strategy", "generation_reference", "work_planning"})


def _aware(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _default_policy(source_class: str, envelope: dict[str, Any]) -> dict[str, bool]:
    if source_class == "public_web_observation":
        return {"topic_planning": True, "owned_strategy": False, "generation_reference": False, "work_planning": True}
    if source_class == "official_authorized":
        owned_ready = bool(envelope.get("authorization_ref")) and bool(envelope.get("account_id"))
        return {"topic_planning": owned_ready, "owned_strategy": owned_ready, "generation_reference": False, "work_planning": owned_ready}
    if source_class == "licensed_vendor":
        cleared = envelope.get("license_status") == "cleared"
        scope = set(map(str, envelope.get("license_scope") or []))
        return {"topic_planning": cleared and "topic_planning" in scope,
                "owned_strategy": False,
                "generation_reference": cleared and "generation_reference" in scope,
                "work_planning": cleared and "work_planning" in scope}
    return {"topic_planning": True, "owned_strategy": False, "generation_reference": False, "work_planning": True}


def validate_envelope(value: Any) -> dict[str, Any]:
    """Validate minimum provenance; never infer a stronger origin or right."""
    envelope = dict(value) if isinstance(value, dict) else {}
    reasons: list[str] = []
    if envelope.get("version") != "intelligence_provenance_v1":
        reasons.append("provenance_version_invalid")
    source_class = str(envelope.get("source_class") or "").strip()
    if source_class not in SOURCE_CLASSES:
        reasons.append("source_class_invalid")
    for field in ("evidence_id", "origin_platform", "collector_id", "content_locator"):
        if not str(envelope.get(field) or "").strip():
            reasons.append(f"{field}_missing")
    for field in ("observed_at", "ingested_at"):
        if not _aware(envelope.get(field)):
            reasons.append(f"{field}_timezone_invalid")
    integrity = envelope.get("integrity") if isinstance(envelope.get("integrity"), dict) else {}
    if not _hash(integrity.get("sha256")):
        reasons.append("integrity_hash_invalid")
    if any(any(part in str(key).casefold() for part in SENSITIVE_PARTS) for key in envelope):
        reasons.append("sensitive_field_forbidden")
    if source_class == "official_authorized":
        if not str(envelope.get("authorization_ref") or "").strip():
            reasons.append("authorization_ref_missing")
        if not str(envelope.get("account_id") or "").strip():
            reasons.append("account_id_missing")
    if source_class == "licensed_vendor":
        if not isinstance(envelope.get("license_scope"), list):
            reasons.append("license_scope_missing")
        if envelope.get("license_status") not in {"cleared", "pending_review", "blocked"}:
            reasons.append("license_status_invalid")
    envelope["use_policy"] = _default_policy(source_class, envelope)
    return {"version": "intelligence_provenance_validation_v1", "passed": not reasons,
            "reason_codes": sorted(set(reasons)), "envelope": envelope}


def can_use(envelope: Any, purpose: str) -> dict[str, Any]:
    """Answer whether a validated item can serve one bounded downstream purpose."""
    result = validate_envelope(envelope)
    canonical_purpose = str(purpose or "").strip()
    if canonical_purpose not in _PURPOSES:
        return {"allowed": False, "reason_codes": ["purpose_invalid"]}
    if not result["passed"]:
        return {"allowed": False, "reason_codes": result["reason_codes"]}
    allowed = result["envelope"]["use_policy"].get(canonical_purpose) is True
    return {"allowed": allowed, "reason_codes": [] if allowed else ["source_not_permitted_for_purpose"]}
