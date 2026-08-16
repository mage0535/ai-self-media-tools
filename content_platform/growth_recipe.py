"""Machine-checkable growth recipe produced before content generation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


TOOL_DEMO_FORMS = {"tool_demo_video", "tool_test_video", "screencast", "tool_review"}


def derive_topic_growth_signals(candidate: dict[str, Any] | None) -> list[str]:
    """Return only evidence-backed growth signals available before generation."""
    candidate = candidate or {}
    signals: list[str] = []
    if float(candidate.get("points") or 0) > 0:
        signals.append("observed_engagement")
    if str(candidate.get("trend_stage") or "").casefold() in {"emerging", "hot", "viral", "viral_candidate"}:
        signals.append("timeliness")
    source = str(candidate.get("source") or "").strip()
    host = urlparse(str(candidate.get("url") or "")).hostname or ""
    if source and host:
        signals.append("source_provenance")
    return list(dict.fromkeys(signals))


def build_growth_recipe(
    *,
    platform: str,
    content_form: str,
    source_matrix: dict[str, Any] | None,
    topic_decision: dict[str, Any] | None,
    tool_selection_plan: dict[str, Any] | None,
    process_evidence: dict[str, Any] | None = None,
    cta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = list((source_matrix or {}).get("attempted_sources") or [])
    statuses = [str(row.get("status") or "unavailable").casefold() for row in sources if isinstance(row, dict)]
    source_status = "success" if any(state in {"success", "ok"} for state in statuses) else "degraded" if any(state == "degraded" for state in statuses) else "unavailable"
    decision = topic_decision or {}
    return {
        "version": "growth_recipe_v1",
        "platform": str(platform or "").casefold(),
        "content_form": str(content_form or "article").casefold(),
        "source_matrix": {"attempted_sources": sources},
        "source_status": source_status,
        "topic_decision": {
            "score": float(decision.get("score") or 0),
            # ``signals`` was emitted by the first auto-routing path.  Keep
            # that evidence valid while persisting one canonical field.
            "growth_signals": [
                str(item)
                for item in (decision.get("growth_signals") or decision.get("signals") or [])
                if str(item).strip()
            ],
        },
        "tool_selection_plan": tool_selection_plan or {},
        "process_evidence": process_evidence or {},
        "cta": cta or {},
    }


def validate_growth_recipe(recipe: dict[str, Any] | None) -> dict[str, Any]:
    recipe = recipe or {}
    failures: list[str] = []
    source_matrix = recipe.get("source_matrix") or {}
    attempted = source_matrix.get("attempted_sources") if isinstance(source_matrix, dict) else []
    if not isinstance(attempted, list) or not attempted:
        failures.append("source_matrix")
    decision = recipe.get("topic_decision") or {}
    if len(decision.get("growth_signals") or []) < 2:
        failures.append("topic_growth_signals")
    if float(decision.get("score") or 0) <= 0:
        failures.append("topic_score")
    selected_tools = (recipe.get("tool_selection_plan") or {}).get("selected_tools") or []
    if not selected_tools:
        failures.append("tool_selection")
    content_form = str(recipe.get("content_form") or "").casefold()
    if content_form in TOOL_DEMO_FORMS:
        evidence = recipe.get("process_evidence") or {}
        if not evidence.get("screenshots") or not evidence.get("tool_names") or not evidence.get("limitations"):
            failures.append("process_evidence")
        cta = recipe.get("cta") or {}
        if not cta.get("deliverable") or not cta.get("question"):
            failures.append("concrete_cta")
    return {"passed": not failures, "failures": failures, "source_status": recipe.get("source_status", "unavailable")}
