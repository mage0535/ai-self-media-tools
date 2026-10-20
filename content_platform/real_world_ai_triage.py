"""Evidence-completeness triage for real-world AI content candidates."""
from __future__ import annotations

from typing import Any


def triage_real_world_ai_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Return a fail-closed research tier without inferring performance claims."""
    row = candidate if isinstance(candidate, dict) else {}
    failures: list[str] = []
    required_evidence: list[str] = ["body_or_native_page_verification_missing"]
    entity_complete = all(str(row.get(key) or "").strip() for key in ("title", "canonical_url", "content_id"))
    if not entity_complete:
        failures.append("entity_traceability_incomplete")
    provenance_complete = all(str(row.get(key) or "").strip() for key in ("source", "collector", "observed_at", "raw_response_hash"))
    if not provenance_complete:
        failures.append("provenance_incomplete")
    positioning = row.get("positioning") if isinstance(row.get("positioning"), dict) else {}
    scene_supported = bool(str(positioning.get("pillar") or "").strip())
    if not scene_supported:
        failures.append("scene_match_unverified")
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    reaction_snapshot = any(key in metrics for key in ("likes", "comments", "views", "heat_value"))
    if not reaction_snapshot:
        failures.append("reaction_snapshot_missing")
    if not row.get("native_verified"):
        required_evidence.append("native_page_visibility_and_author_verification_missing")
    required_evidence.extend([
        "actor_input_process_outcome_boundary_handoff_review",
        "measurement_baseline_and_method_review",
        "topic_author_and_commercial_narrative_deduplication",
        "second_comparable_metric_snapshot_for_momentum_claims",
    ])
    score = sum((entity_complete, provenance_complete, scene_supported, reaction_snapshot))
    tier = "observe_only" if score <= 2 else "research_candidate" if score <= 4 else "manual_evidence_required"
    return {
        "version": "real_world_ai_triage_v1",
        "tier": tier,
        "evidence_completeness_score": score,
        "failures": failures,
        "required_evidence": required_evidence,
        "generation_only": True,
        "auto_selection_eligible": False,
        "viral_claim_eligible": False,
        "score_meaning": "evidence completeness only; not popularity, impact, or outcome quality",
    }
