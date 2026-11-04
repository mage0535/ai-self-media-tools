"""Fail-closed preflight for real platform video rendering."""
from __future__ import annotations

import json
from pathlib import Path


class VideoPreflightError(ValueError):
    pass


REQUIRED_FIELDS = (
    "platform",
    "research_pack",
    "topic_selection",
    "content_brief",
    "asset_plan",
    "quality_gates",
)


def validate_video_preflight(output_dir: Path, platform: str, *, store=None) -> dict:
    path = Path(output_dir) / "video_preflight.json"
    if not path.is_file():
        raise VideoPreflightError("video_preflight.json missing: research and topic gates must run before rendering")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VideoPreflightError(f"video_preflight.json invalid: {exc}") from exc
    failures = []
    if str(payload.get("platform") or "").casefold() != str(platform or "").casefold():
        failures.append("platform_identity_mismatch")
    for field in REQUIRED_FIELDS[1:]:
        value = payload.get(field)
        if not value:
            failures.append(f"{field}_missing")
    research = payload.get("research_pack") or {}
    original=payload.get("content_mode")=="original_knowledge"
    if original:
        import os
        from .store import Store
        from .original_knowledge import read_original_inputs
        from .video_preflight_inputs import read_bound_file,_step
        canonical=os.environ.get("NATIVE_VIDEO_STORE_PATH")
        if store is None:
            if not canonical:
                raise VideoPreflightError("original_native_store_receipt_required")
            store=Store(canonical)
        ref=payload.get("original_knowledge_ref")
        proof=read_original_inputs(store,payload.get("job_id"),ref)
        matches=[json.loads(row["detail_json"]) for row in store.events(payload["job_id"])
                 if row["event"]=="native_video_preflight_bound"]
        if not any(read_bound_file(store,payload["job_id"],row,"native_video_preflight_bound",platform)==payload for row in matches):
            raise VideoPreflightError("original_preflight_store_receipt_required")
        if (len(proof["documents"])!=2 or not proof.get("demo") or len(proof["beat_sources"])!=8
                or research.get("platform_native_verified") is not False or payload.get("allow_degraded_render")):
            raise VideoPreflightError("original_factual_contract_invalid")
        receipts=payload.get("quality_gates",{}).get("native_step_receipts") or {}
        required={"collect_native_source_inputs","run_content_hygiene","generate_content","validate_factual_claims",
                  "run_safety_gate","run_quality_gate","original_copy_dedup"}
        if set(receipts)!=required:
            raise VideoPreflightError("original_complete_native_gate_receipts_required")
        for name,record in receipts.items():
            if _step(store,payload["job_id"],name)[1]!=record:
                raise VideoPreflightError("original_native_gate_receipt_changed")
    if not original and int(research.get("attempted_sources") or 0) < 5:
        failures.append("research_attempted_sources_below_5")
    if not original and int(research.get("successful_sources") or 0) < 3:
        failures.append("research_successful_sources_below_3")
    # Owner rule 11-02: where the platform cannot be read, a labelled same-genre cross-platform benchmark is the
    # research evidence (overnight lanes); it is never treated as native and is never a degraded override.
    labelled_cross_platform = (payload.get("version") == "overnight_video_preflight_v1"
                               and research.get("evidence_scope") == "cross_platform"
                               and bool(str(research.get("cross_platform_source") or "").strip())
                               and int(research.get("hot_viral_sample_count") or 0) > 0)
    if not original and research.get("platform_native_verified") is not True and not labelled_cross_platform:
        # A degraded research pack is evidence of a blocker, not permission to render.
        # Only an explicit, separately reviewed override may produce a degraded draft.
        if not (research.get("degraded_source") is True and payload.get("allow_degraded_render") is True):
            failures.append("research_native_evidence_required")
    topic = payload.get("topic_selection") or {}
    if topic.get("selected") is not True or not str(topic.get("reason") or "").strip():
        failures.append("topic_selection_not_committed")
    gates = payload.get("quality_gates") or {}
    if gates.get("allow_render") is not True:
        failures.append("quality_gates_do_not_allow_render")
    if failures:
        raise VideoPreflightError(",".join(failures))
    return payload
