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

IMAGE_TEXT_CARD_REQUIRED_KEYS = {
    "version",
    "platform",
    "content_type",
    "card_count",
    "story_arc",
    "style_matrix",
    "layout_matrix",
    "card_to_asset_binding",
    "readability_contract",
    "engagement_contract",
    "source_policy",
    "tool_candidates",
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


def build_image_text_card_recipe(
    *,
    platform: str,
    content_type: str = "image_text_cards",
    title: str = "",
    cards: list[Any] | None = None,
    sections: list[Any] | None = None,
    content_goal: str = "",
) -> dict[str, Any]:
    """Build a reusable recipe for image-text cards, carousels, and newspic posts.

    This sits above concrete renderers. It records why a batch should look the
    way it does, which free/approved tools may be used, and which layout/source
    constraints the quality gate must enforce.
    """

    valid_cards = [item for item in (cards or []) if isinstance(item, dict)]
    normalized_sections = _normalize_sections(sections, title)
    card_count = len(valid_cards) or max(3, min(9, len(normalized_sections) + 2))
    roles = _card_roles(valid_cards, card_count)
    layouts = _distinct_values(valid_cards, "layout", ["hero", "split", "timeline", "checklist", "quote", "summary_cta"])
    palettes = _distinct_values(valid_cards, "palette", ["editorial_blue", "warm_field", "minimal_ink", "fresh_green", "dark_focus"])
    recipe = {
        "version": "image_text_card_recipe_v1",
        "platform": platform,
        "content_type": content_type or "image_text_cards",
        "card_count": card_count,
        "story_arc": {
            "roles": roles,
            "first_card": "hook plus concrete payoff",
            "middle_cards": "one useful idea per card with evidence, example, or checklist",
            "last_card": "single CTA for comment, save, follow, or keyword reply",
        },
        "style_matrix": {
            "palette_variants": palettes[: max(3, min(5, card_count))],
            "typography_scale": "title 48-72px / body 22-40px / label 10-14px",
            "tone_variants": ["editorial", "case_note", "field_report", "checklist"],
            "text_arrangement_variants": ["horizontal", "vertical_label", "staggered_blocks", "quote_focus", "timeline_steps"],
        },
        "layout_matrix": {
            "layout_variants": layouts[: max(3, min(6, card_count))],
            "foreground_effects": ["number_badge", "highlight_strip", "callout_box", "progress_marker"],
            "background_effects": ["real_scene_crop", "soft_blur_depth", "low_opacity_overlay", "subject_spotlight"],
            "transition_guidance": "video conversion may animate foreground text and background motion separately",
        },
        "card_to_asset_binding": [
            {
                "card": idx,
                "role": roles[min(idx - 1, len(roles) - 1)],
                "section": _section_id(normalized_sections, idx),
                "asset_subject": _asset_subject(valid_cards, idx, title),
                "match_reason": _asset_match_reason(valid_cards, idx),
            }
            for idx in range(1, card_count + 1)
        ],
        "readability_contract": {
            "ratio": "3:4 preferred for image posts; platform may override",
            "safe_margin_px_min": 30,
            "line_height": "1.6-1.8",
            "one_idea_per_card": True,
            "mobile_first": True,
            "overflow_forbidden": True,
        },
        "engagement_contract": {
            "hook_required": True,
            "save_reason_required": True,
            "single_cta_required": True,
            "payoff_interval_cards": 1,
            "content_goal": content_goal or "increase full reads, saves, shares, comments, and follow conversion",
        },
        "source_policy": {
            "primary": ["licensed_real_scene_assets", "topic_matched_ai_generated_images", "ai_edit_real_material"],
            "free_first_providers": ["cloudflare_workers_ai_free_tier", "pollinations", "pexels", "pixabay", "unsplash"],
            "optional_external_mcp_candidates": ["paper_design_mcp", "postnitro_mcp", "contentdrips_mcp"],
            "forbidden": ["css_gradient_as_primary_background", "solid_color_placeholder", "random_unmatched_stock_photo"],
            "license_manifest_required": True,
        },
        "tool_candidates": {
            "strategy": ["growth_strategy_latest", "platform_source_matrix"],
            "design": ["knowledge-card-designer", "wechat_image_post_cards", "markdown_image_generator_style", "carousel_design_patterns"],
            "image_sources": ["cloudflare_workers_ai", "pollinations", "pexels", "pixabay", "unsplash"],
            "quality": ["validate_wechat_image_post_packet", "validate_image_text_card_recipe", "visual_gate"],
        },
        "fatigue_check": {
            "lookback_days": 7,
            "recent_core_fingerprints": [],
            "duplicate_found": False,
        },
        "human_viewer_reason": "the card batch has a visible hook, varied rhythm, topic-matched visuals, and saveable takeaways instead of decorative screenshots",
    }
    recipe["core_fingerprint"] = image_text_card_core_fingerprint(recipe)
    recipe["fingerprint"] = _fingerprint({**recipe, "title_signature": _text_signature(title)})
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
        "executed_count": len([item for item in records.values() if isinstance(item, dict) and item.get("status") in {"ok", "generated"}]),
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


def validate_image_text_card_recipe(recipe: dict[str, Any] | None) -> dict[str, Any]:
    failures = _missing_failures(recipe, IMAGE_TEXT_CARD_REQUIRED_KEYS, "image_text_card_recipe")
    if not failures and isinstance(recipe, dict):
        if int(recipe.get("card_count") or 0) < 3:
            failures.append("image_text_card_recipe card_count must be at least 3")
        story = recipe.get("story_arc") if isinstance(recipe.get("story_arc"), dict) else {}
        roles = [str(item).casefold() for item in (story.get("roles") or [])]
        if "cover" not in roles or not any(role in {"cta", "summary_cta"} for role in roles):
            failures.append("image_text_card_recipe story_arc must include cover and CTA roles")
        styles = recipe.get("style_matrix") if isinstance(recipe.get("style_matrix"), dict) else {}
        layouts = recipe.get("layout_matrix") if isinstance(recipe.get("layout_matrix"), dict) else {}
        if len(styles.get("palette_variants") or []) < 3:
            failures.append("image_text_card_recipe requires at least 3 palette variants")
        if len(styles.get("text_arrangement_variants") or []) < 3:
            failures.append("image_text_card_recipe requires at least 3 text arrangement variants")
        if len(layouts.get("layout_variants") or []) < 3:
            failures.append("image_text_card_recipe requires at least 3 layout variants")
        if not layouts.get("foreground_effects") or not layouts.get("background_effects"):
            failures.append("image_text_card_recipe must separate foreground and background effects")
        bindings = recipe.get("card_to_asset_binding") if isinstance(recipe.get("card_to_asset_binding"), list) else []
        if len(bindings) < min(3, int(recipe.get("card_count") or 0)):
            failures.append("image_text_card_recipe card_to_asset_binding must cover at least 3 cards")
        if not all(isinstance(item, dict) and item.get("asset_subject") and item.get("match_reason") for item in bindings):
            failures.append("image_text_card_recipe every asset binding needs subject and match reason")
        source = recipe.get("source_policy") if isinstance(recipe.get("source_policy"), dict) else {}
        forbidden = {str(item).casefold() for item in (source.get("forbidden") or [])}
        if source.get("license_manifest_required") is not True:
            failures.append("image_text_card_recipe must require license manifest")
        if not {"css_gradient_as_primary_background", "random_unmatched_stock_photo"}.issubset(forbidden):
            failures.append("image_text_card_recipe must forbid gradient primary backgrounds and random stock photos")
        engagement = recipe.get("engagement_contract") if isinstance(recipe.get("engagement_contract"), dict) else {}
        if not all(engagement.get(key) is True for key in ["hook_required", "save_reason_required", "single_cta_required"]):
            failures.append("image_text_card_recipe engagement contract must require hook, save reason, and single CTA")
        fatigue = recipe.get("fatigue_check") if isinstance(recipe.get("fatigue_check"), dict) else {}
        if int(fatigue.get("lookback_days") or 0) < 7 or fatigue.get("duplicate_found") is True:
            failures.append("image_text_card_recipe fatigue_check must use 7-day lookback and no duplicate")
        if not recipe.get("core_fingerprint") or not recipe.get("fingerprint"):
            failures.append("image_text_card_recipe fingerprints missing")
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


def image_text_card_core_fingerprint(recipe: dict[str, Any]) -> str:
    stable = {
        "content_type": recipe.get("content_type"),
        "story_arc": recipe.get("story_arc"),
        "style_matrix": recipe.get("style_matrix"),
        "layout_matrix": recipe.get("layout_matrix"),
        "source_policy": recipe.get("source_policy"),
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


def _card_roles(cards: list[dict[str, Any]], card_count: int) -> list[str]:
    roles = [str(card.get("role") or "").strip() for card in cards if str(card.get("role") or "").strip()]
    if roles:
        return roles
    if card_count <= 3:
        return ["cover", "content", "cta"]
    return ["cover", *["content" for _ in range(max(1, card_count - 2))], "cta"]


def _distinct_values(cards: list[dict[str, Any]], key: str, fallback: list[str]) -> list[str]:
    values = []
    for card in cards:
        value = str(card.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    for value in fallback:
        if value not in values:
            values.append(value)
    return values


def _section_id(sections: list[dict[str, Any]], idx: int) -> str:
    if not sections:
        return f"section_{idx}"
    item = sections[min(idx - 1, len(sections) - 1)]
    return str(item.get("id") or item.get("section") or f"section_{idx}")


def _asset_subject(cards: list[dict[str, Any]], idx: int, title: str) -> str:
    if idx <= len(cards):
        card = cards[idx - 1]
        background = card.get("background") if isinstance(card.get("background"), dict) else {}
        return str(card.get("visual_subject") or background.get("query") or card.get("title") or title or f"card_{idx}")
    return str(title or f"card_{idx}")


def _asset_match_reason(cards: list[dict[str, Any]], idx: int) -> str:
    if idx <= len(cards):
        card = cards[idx - 1]
        background = card.get("background") if isinstance(card.get("background"), dict) else {}
        return str(background.get("match_reason") or card.get("match_reason") or "asset must directly explain this card")
    return "asset must directly explain this card"


def _text_signature(text: str) -> str:
    normalized = " ".join(str(text or "").split())[:500]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _fingerprint(value: dict[str, Any]) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()
