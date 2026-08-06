"""Content recipe contracts for article and knowledge-card workflows."""

from __future__ import annotations

import hashlib
import json
from typing import Any


ARTICLE_REQUIRED_KEYS = {
    "version",
    "content_type",
    "platform",
    "structure_plan",
    "internal_variation_plan",
    "section_to_visual_binding",
    "template_alternatives",
    "fatigue_check",
    "human_viewer_reason",
    "first_screen_contract",
    "payoff_schedule",
}

KNOWLEDGE_CARD_REQUIRED_KEYS = {
    "version",
    "platform",
    "card_count",
    "card_roles",
    "layout_variants",
    "typography_contract",
    "section_to_card_binding",
    "fatigue_check",
    "human_viewer_reason",
}


def build_article_recipe(
    *,
    platform: str,
    content_type: str,
    title: str,
    body: str,
    sections: list[Any] | None = None,
    section_image_map: list[Any] | None = None,
    embedded_knowledge_cards: list[Any] | None = None,
    visual_template_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = _normalize_sections(sections, body)
    mapping = [item for item in (section_image_map or []) if isinstance(item, dict)]
    cards = [item for item in (embedded_knowledge_cards or []) if isinstance(item, dict)]
    selected_template = str((visual_template_selection or {}).get("selected") or "article-default")
    alternatives = (visual_template_selection or {}).get("ranked_scores") or []
    recipe = {
        "version": "content_recipe_v1",
        "content_type": content_type or "article",
        "platform": platform,
        "structure_plan": {
            "selected_template": selected_template,
            "section_count": len(sections),
            "section_roles": [str(item.get("role") or item.get("id") or "") for item in sections],
        },
        "internal_variation_plan": {
            "required_variation_count": max(3, min(6, len(sections))),
            "variation_axes": ["opening_hook", "case_or_proof", "visual_break", "checklist_or_summary", "cta"],
            "paragraph_rhythm": "vary hook, explanation, example, checklist, and boundary sections",
        },
        "section_to_visual_binding": [
            {
                "section": item.get("section") or item.get("id") or f"section_{idx}",
                "visual": item.get("image") or item.get("asset_id") or f"planned_visual_{idx}",
                "match_reason": item.get("purpose") or item.get("match_reason") or "visual must explain adjacent section",
            }
            for idx, item in enumerate(mapping, 1)
        ],
        "template_alternatives": _template_alternatives(selected_template, alternatives),
        "fatigue_check": {
            "lookback_days": 7,
            "recent_core_fingerprints": [],
            "duplicate_found": False,
        },
        "human_viewer_reason": "reader sees the payoff early, gets section-level visual breaks, and can save the checklist",
        "first_screen_contract": {
            "title": str(title or "")[:80],
            "promise": "state pain, result, and why now in the opening screen",
        },
        "payoff_schedule": _payoff_schedule(sections),
        "knowledge_card_summary": {
            "card_count": len(cards),
            "roles": [str(card.get("card_type") or card.get("layout") or "") for card in cards],
        },
    }
    recipe["core_fingerprint"] = article_core_fingerprint(recipe)
    recipe["fingerprint"] = _fingerprint({**recipe, "title": title, "body_signature": _text_signature(body)})
    return recipe


def build_knowledge_card_recipe(
    *,
    platform: str,
    cards: list[Any] | None = None,
    content_type: str = "knowledge_cards",
) -> dict[str, Any]:
    valid_cards = [item for item in (cards or []) if isinstance(item, dict)]
    roles = [str(card.get("card_type") or card.get("information_value") or f"card_{idx}") for idx, card in enumerate(valid_cards, 1)]
    layouts = [str(card.get("layout") or "") for card in valid_cards if str(card.get("layout") or "").strip()]
    recipe = {
        "version": "knowledge_card_recipe_v1",
        "content_type": content_type,
        "platform": platform,
        "card_count": len(valid_cards),
        "card_roles": roles,
        "layout_variants": sorted(set(layouts)),
        "typography_contract": {
            "hierarchy": "4:2:1",
            "safe_margin_px_min": 30,
            "line_height": "1.6-1.8",
            "max_palette_colors": 3,
        },
        "section_to_card_binding": [
            {
                "section": card.get("section") or card.get("script_beat") or f"card_{idx}",
                "card_role": card.get("card_type") or card.get("layout") or "knowledge_point",
                "information_value": card.get("information_value") or "card must add reusable information value",
            }
            for idx, card in enumerate(valid_cards, 1)
        ],
        "fatigue_check": {
            "lookback_days": 7,
            "recent_core_fingerprints": [],
            "duplicate_found": False,
        },
        "human_viewer_reason": "each card has a distinct information task and save/share value",
    }
    recipe["core_fingerprint"] = knowledge_card_core_fingerprint(recipe)
    recipe["fingerprint"] = _fingerprint(recipe)
    return recipe


def build_tool_invocation_manifest(
    *,
    planned_tools: dict[str, Any] | None = None,
    invocations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planned = planned_tools or {}
    records = invocations or {}
    return {
        "version": "tool_invocation_manifest_v1",
        "planned_tools": planned,
        "invocations": records,
        "executed_count": len([item for item in records.values() if isinstance(item, dict) and item.get("status") in {"ok", "planned_internal", "generated"}]),
        "missing_tools": [name for name in planned if name not in records],
    }


def validate_article_recipe(recipe: dict[str, Any] | None) -> dict[str, Any]:
    failures = _missing_failures(recipe, ARTICLE_REQUIRED_KEYS, "article_recipe")
    if not failures and isinstance(recipe, dict):
        bindings = recipe.get("section_to_visual_binding") if isinstance(recipe.get("section_to_visual_binding"), list) else []
        alternatives = recipe.get("template_alternatives") if isinstance(recipe.get("template_alternatives"), list) else []
        variation = recipe.get("internal_variation_plan") if isinstance(recipe.get("internal_variation_plan"), dict) else {}
        fatigue = recipe.get("fatigue_check") if isinstance(recipe.get("fatigue_check"), dict) else {}
        payoff = recipe.get("payoff_schedule") if isinstance(recipe.get("payoff_schedule"), list) else []
        if len(bindings) < 3:
            failures.append("section_to_visual_binding must include at least 3 bindings")
        if len(alternatives) < 2:
            failures.append("template_alternatives must include selected plus at least one alternative")
        if int(variation.get("required_variation_count") or 0) < 3:
            failures.append("internal_variation_plan requires at least 3 variations")
        if int(fatigue.get("lookback_days") or 0) < 7 or fatigue.get("duplicate_found") is True:
            failures.append("fatigue_check must use 7-day lookback and no duplicate")
        if len(payoff) < 3:
            failures.append("payoff_schedule must include at least 3 payoff points")
        if not recipe.get("core_fingerprint") or not recipe.get("fingerprint"):
            failures.append("recipe fingerprints missing")
    return _validation_result(failures)


def validate_knowledge_card_recipe(recipe: dict[str, Any] | None) -> dict[str, Any]:
    failures = _missing_failures(recipe, KNOWLEDGE_CARD_REQUIRED_KEYS, "knowledge_card_recipe")
    if not failures and isinstance(recipe, dict):
        if int(recipe.get("card_count") or 0) < 3:
            failures.append("card_count must be at least 3")
        if len(recipe.get("layout_variants") or []) < 2:
            failures.append("layout_variants must include at least 2 layouts")
        if len(recipe.get("section_to_card_binding") or []) < 3:
            failures.append("section_to_card_binding must include at least 3 bindings")
        fatigue = recipe.get("fatigue_check") if isinstance(recipe.get("fatigue_check"), dict) else {}
        if int(fatigue.get("lookback_days") or 0) < 7 or fatigue.get("duplicate_found") is True:
            failures.append("fatigue_check must use 7-day lookback and no duplicate")
        if not recipe.get("core_fingerprint") or not recipe.get("fingerprint"):
            failures.append("recipe fingerprints missing")
    return _validation_result(failures)


def validate_tool_invocation_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(manifest, dict) or not manifest:
        failures.append("tool_invocation_manifest missing")
    else:
        planned = manifest.get("planned_tools") if isinstance(manifest.get("planned_tools"), dict) else {}
        invocations = manifest.get("invocations") if isinstance(manifest.get("invocations"), dict) else {}
        missing = manifest.get("missing_tools") if isinstance(manifest.get("missing_tools"), list) else []
        if len(planned) < 3:
            failures.append("planned_tools must include at least 3 tools")
        if len(invocations) < 3:
            failures.append("invocations must include at least 3 tool records")
        if missing:
            failures.append("all planned tools must have invocation records")
    return _validation_result(failures)


def article_core_fingerprint(recipe: dict[str, Any]) -> str:
    stable = {
        "content_type": recipe.get("content_type"),
        "structure_plan": recipe.get("structure_plan"),
        "internal_variation_plan": recipe.get("internal_variation_plan"),
        "template_alternatives": recipe.get("template_alternatives"),
    }
    return _fingerprint(stable)


def knowledge_card_core_fingerprint(recipe: dict[str, Any]) -> str:
    stable = {
        "content_type": recipe.get("content_type"),
        "card_roles": recipe.get("card_roles"),
        "layout_variants": recipe.get("layout_variants"),
        "typography_contract": recipe.get("typography_contract"),
    }
    return _fingerprint(stable)


def _missing_failures(recipe: dict[str, Any] | None, keys: set[str], label: str) -> list[str]:
    if not isinstance(recipe, dict) or not recipe:
        return [f"{label} missing"]
    return [f"missing {key}" for key in sorted(keys) if recipe.get(key) in (None, "", [], {})]


def _validation_result(failures: list[str]) -> dict[str, Any]:
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["content_recipe"] if failures else []}


def _template_alternatives(selected: str, ranked_scores: list[Any]) -> list[dict[str, Any]]:
    rows = [item for item in ranked_scores if isinstance(item, dict) and item.get("template")]
    if not rows:
        rows = [{"template": selected, "score": 0.8}]
    if len(rows) == 1:
        rows.append({"template": "alternate_" + selected, "score": 0.65})
    return rows[:3]


def _normalize_sections(sections: list[Any] | None, body: str) -> list[dict[str, Any]]:
    rows = []
    for idx, item in enumerate(sections or [], 1):
        if isinstance(item, dict):
            rows.append({"id": item.get("id") or item.get("section") or f"section_{idx}", "role": item.get("role") or "body"})
        else:
            rows.append({"id": str(item), "role": "body"})
    if rows:
        return rows
    chunks = [part.strip() for part in str(body or "").split("\n\n") if part.strip()]
    return [{"id": f"section_{idx}", "role": "body"} for idx, _ in enumerate(chunks[:5], 1)] or [{"id": "section_1", "role": "body"}]


def _payoff_schedule(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    labels = ["hook", "proof", "method", "checklist", "cta"]
    for idx, section in enumerate(sections[:5], 1):
        rows.append({"position": idx, "section": section.get("id"), "payoff": labels[min(idx - 1, len(labels) - 1)]})
    return rows


def _text_signature(text: str) -> str:
    normalized = " ".join(str(text or "").split())[:500]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _fingerprint(value: dict[str, Any]) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()
