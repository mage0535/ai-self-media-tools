"""Deterministic, fail-closed routing for creative content structures."""

from __future__ import annotations

from copy import deepcopy


_REQUIRED_CAPABILITIES = (
    "supported_visual_modes",
    "asset_roles",
    "group_motions",
    "transitions",
    "audio_profiles",
)


def _capabilities(
    visual_modes: tuple[str, ...],
    asset_roles: tuple[str, ...],
    group_motions: tuple[str, ...],
    transitions: tuple[str, ...],
    audio_profiles: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    return dict(
        zip(
            _REQUIRED_CAPABILITIES,
            (visual_modes, asset_roles, group_motions, transitions, audio_profiles),
            strict=True,
        )
    )


_REGISTRY = {
    "document_workflow": {
        "capabilities": _capabilities(
            ("document", "annotated_page"),
            ("source_document", "annotation", "result"),
            ("page_stack", "callout_reveal"),
            ("page_turn", "match_cut"),
            ("focused", "instructional"),
        )
    },
    "screencast": {
        "capabilities": _capabilities(
            ("screen_recording", "cursor_focus"),
            ("interface", "cursor", "step_label"),
            ("guided_pan", "cursor_follow"),
            ("cut_on_action", "zoom_bridge"),
            ("tutorial", "calm_technical"),
        )
    },
    "terminal_diff": {
        "capabilities": _capabilities(
            ("terminal", "code_diff"),
            ("command", "before_code", "after_code"),
            ("line_highlight", "diff_wipe"),
            ("hard_cut", "diff_match"),
            ("technical", "percussive_focus"),
        )
    },
    "before_after": {
        "capabilities": _capabilities(
            ("comparison", "reveal"),
            ("before", "after", "proof"),
            ("split_reveal", "result_hold"),
            ("wipe", "match_cut"),
            ("transformation", "uplifting"),
        )
    },
    "diagnostic_console": {
        "capabilities": _capabilities(
            ("dashboard", "console"),
            ("symptom", "telemetry", "diagnosis"),
            ("alert_pulse", "trace_follow"),
            ("signal_cut", "drill_down"),
            ("investigative", "low_pulse"),
        )
    },
    "split_evidence": {
        "capabilities": _capabilities(
            ("split_screen", "evidence_board"),
            ("claim", "source", "counterpoint"),
            ("paired_track", "evidence_pin"),
            ("parallel_cut", "evidence_match"),
            ("analytical", "restrained"),
        )
    },
    "timeline_process": {
        "capabilities": _capabilities(
            ("timeline", "process_map"),
            ("milestone", "dependency", "outcome"),
            ("timeline_flow", "milestone_pop"),
            ("time_jump", "progress_bridge"),
            ("progressive", "steady_momentum"),
        )
    },
    "human_handoff_case": {
        "capabilities": _capabilities(
            ("real_scene", "localized_annotation", "decision_point", "boundary_case"),
            ("environment", "ai_output", "human_reviewer", "exception"),
            ("local_callout", "decision_reveal", "boundary_step"),
            ("stable_cut", "subject_match", "evidence_cut"),
            ("documentary", "restrained_instrumental"),
        )
    },
}


def get_structure_registry() -> dict[str, dict]:
    """Return a defensive copy of the built-in capability registry."""
    return deepcopy(_REGISTRY)


_SIGNATURES = {
    "document_workflow": ("problem-doc-steps-result", "artifact_first", "stepwise", "page_stack", "guided_annotations", "page_turn", "document_closeups"),
    "screencast": ("goal-action-check", "outcome_preview", "procedural", "screen_stage", "cursor_guidance", "cut_on_action", "screen_punch_in"),
    "terminal_diff": ("failure-command-diff-proof", "broken_line", "contrastive", "terminal_columns", "line_tracking", "diff_match", "code_detail"),
    "before_after": ("baseline-change-reveal-proof", "result_flash", "transformation", "comparison_split", "split_reveal", "wipe", "matched_frames"),
    "diagnostic_console": ("symptom-signal-hypothesis-fix", "anomaly_alert", "diagnostic", "console_dashboard", "trace_follow", "drill_down", "telemetry_macro"),
    "split_evidence": ("claim-source-counterpoint-verdict", "contested_claim", "argumentative", "evidence_split", "paired_track", "parallel_cut", "source_insert"),
    "timeline_process": ("origin-milestones-turning_point-outcome", "future_state", "chronological", "timeline_track", "milestone_flow", "time_jump", "temporal_sequence"),
    "human_handoff_case": ("scene-ai_signal-human_decision-boundary", "decision_interrupt", "operational", "scene_anchored", "localized_semantic_motion", "subject_match", "environment_detail"),
}
_SIGNATURE_FIELDS = (
    "scene_structure_signature",
    "hook_pattern",
    "copy_structure",
    "layout_family",
    "motion_grammar",
    "transition_grammar",
    "shot_grammar",
)


class UnsupportedRouteValue(ValueError):
    """Raised when routing input is outside the closed capability registry."""


class RepeatedStructureError(ValueError):
    """Raised when a candidate is too similar to recent structural history."""


class InvalidExternalCandidate(ValueError):
    """Raised when an external candidate lacks auditable provenance."""


_SUPPORTED_PLATFORMS = {
    "wechat",
    "juejin",
    "bilibili",
    "douyin",
    "douyin_ai",
    "douyin_pet",
    "xiaohongshu",
    "tiktok",
    "youtube",
    "youtube_shorts",
    "youtube_long_form",
    "kuaishou",
    "shipinhao",
}
_SUPPORTED_VIEWER_JOBS = {
    "follow a workflow",
    "reproduce steps",
    "review a change",
    "judge the result",
    "find root cause",
    "compare evidence",
    "understand progression",
    "understand human handoff",
}
_ROUTING = {
    "document_workflow": {"content_types": {"tutorial", "workflow"}, "evidence": {"document", "annotations", "screenshots"}, "platforms": {"wechat", "juejin"}, "jobs": {"follow", "workflow", "apply"}},
    "screencast": {"content_types": {"tutorial", "demo"}, "evidence": {"screen_recording", "interface", "cursor"}, "platforms": {"bilibili", "douyin"}, "jobs": {"reproduce", "steps", "learn"}},
    "terminal_diff": {"content_types": {"engineering_change", "code_review"}, "evidence": {"terminal", "code_diff", "patch"}, "platforms": {"juejin", "bilibili"}, "jobs": {"review", "change", "verify"}},
    "before_after": {"content_types": {"case_study", "transformation"}, "evidence": {"before", "after", "result"}, "platforms": {"douyin", "xiaohongshu"}, "jobs": {"judge", "result", "compare"}},
    "diagnostic_console": {"content_types": {"incident", "diagnostic"}, "evidence": {"logs", "metrics", "trace"}, "platforms": {"bilibili", "juejin"}, "jobs": {"root", "cause", "diagnose"}},
    "split_evidence": {"content_types": {"analysis", "comparison"}, "evidence": {"claims", "citations", "sources"}, "platforms": {"wechat", "xiaohongshu"}, "jobs": {"compare", "evidence", "decide"}},
    "timeline_process": {"content_types": {"process", "history"}, "evidence": {"milestones", "dates", "sequence"}, "platforms": {"wechat", "xiaohongshu"}, "jobs": {"progression", "timeline", "understand"}},
    "human_handoff_case": {
        "content_types": {"human_handoff_case"},
        "evidence": {"real_scene", "localized_annotation", "human_decision", "boundary_case"},
        "platforms": {"douyin", "tiktok", "youtube", "kuaishou", "shipinhao", "bilibili"},
        "jobs": {"human", "handoff", "decision"},
    },
}


def _signature(family: str) -> dict[str, str]:
    return dict(zip(_SIGNATURE_FIELDS, _SIGNATURES[family], strict=True))


def fingerprint_structure(structure: dict) -> dict[str, str]:
    """Return only structural dimensions; decorative fields never add novelty."""
    source = structure.get("signature", structure)
    missing = [field for field in _SIGNATURE_FIELDS if not source.get(field)]
    if missing:
        raise ValueError(f"missing structural fingerprint fields: {', '.join(missing)}")
    return {field: source[field] for field in _SIGNATURE_FIELDS}


def _is_similar(left: dict, right: dict) -> bool:
    left_fp = fingerprint_structure(left)
    right_fp = fingerprint_structure(right)
    differences = sum(left_fp[field] != right_fp[field] for field in _SIGNATURE_FIELDS)
    return differences < 3


def route_creative_structure(
    *,
    content_type: str,
    evidence_shapes: list[str] | tuple[str, ...],
    platform: str,
    viewer_job: str,
    recent_fingerprints: list[dict] | tuple[dict, ...] = (),
    history_window: int = 5,
    external_candidates: list[dict] | tuple[dict, ...] = (),
) -> dict:
    """Select the best matching built-in structure from explicit content evidence."""
    supported_types = set().union(*(rules["content_types"] for rules in _ROUTING.values()))
    supported_evidence = set().union(*(rules["evidence"] for rules in _ROUTING.values()))
    invalid = {
        "content_type": content_type not in supported_types,
        "evidence_shapes": not evidence_shapes or bool(set(evidence_shapes) - supported_evidence),
        "platform": platform not in _SUPPORTED_PLATFORMS,
        "viewer_job": viewer_job not in _SUPPORTED_VIEWER_JOBS,
    }
    rejected = [field for field, is_invalid in invalid.items() if is_invalid]
    if rejected:
        raise UnsupportedRouteValue(f"unsupported route value(s): {', '.join(rejected)}")

    evidence = set(evidence_shapes)
    job_tokens = set(viewer_job.lower().split())
    ranked = []
    for order, (family, rules) in enumerate(_ROUTING.items()):
        score = 5 * len(evidence & rules["evidence"])
        score += 3 * int(content_type in rules["content_types"])
        score += 2 * len(job_tokens & rules["jobs"])
        score += int(platform in rules["platforms"])
        ranked.append((score, -order, family))
    _, _, family = max(ranked)
    selected = {
        "family": family,
        "source": "builtin",
        "signature": _signature(family),
        "capabilities": deepcopy(_REGISTRY[family]["capabilities"]),
    }
    if history_window < 1:
        raise ValueError("history_window must be at least 1")
    if any(_is_similar(selected, previous) for previous in recent_fingerprints[-history_window:]):
        raise RepeatedStructureError(
            f"structure {family!r} is too similar to the last {history_window} fingerprints"
        )
    reviewed_external = []
    for candidate in external_candidates:
        missing = [key for key in ("url", "license", "source_hash") if not candidate.get(key)]
        if missing:
            raise InvalidExternalCandidate(
                f"external candidate missing provenance: {', '.join(missing)}"
            )
        if candidate.get("origin") not in {"github", "public_web"}:
            raise InvalidExternalCandidate("external candidate origin must be github or public_web")
        if candidate.get("family") not in _REGISTRY:
            raise InvalidExternalCandidate("external candidate uses an unsupported structure family")
        if not str(candidate["url"]).startswith(("https://", "http://")):
            raise InvalidExternalCandidate("external candidate URL must be absolute HTTP(S)")
        row = deepcopy(candidate)
        selectable = bool(candidate.get("verified"))
        row.update(
            status="verified_candidate" if selectable else "candidate",
            selectable=selectable,
        )
        reviewed_external.append(row)
    return {
        "selected": selected,
        "external_candidates": reviewed_external,
        "selection_basis": {
            "content_type": content_type,
            "evidence_shapes": list(evidence_shapes),
            "platform": platform,
            "viewer_job": viewer_job,
        },
    }
