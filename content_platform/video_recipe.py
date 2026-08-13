"""Visual recipe planning and validation for generated videos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "video_effect_modules.json"


DEFAULT_REQUIRED_KEYS = {
    "template_family",
    "modules",
    "style_variants",
    "asset_strategy",
    "selection_reason",
    "differentiation_reason",
    "scene_asset_match",
    "avoid",
}


def load_effect_module_registry(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path or DEFAULT_REGISTRY)
    if not source.is_file():
        return {"version": "video_effect_modules_v1", "modules": {}, "template_families": {}}
    return json.loads(source.read_text(encoding="utf-8-sig"))


def build_visual_recipe(
    plan: dict[str, Any] | None,
    *,
    script_body: str = "",
    title: str = "",
    cinema_scenes: list[dict[str, Any]] | None = None,
    shotcraft_plan: dict[str, Any] | None = None,
    visual_assets: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a conservative recipe from the existing plan and verified modules."""
    plan = plan or {}
    explicit = plan.get("visual_recipe")
    if isinstance(explicit, dict) and explicit:
        recipe = dict(explicit)
    else:
        registry = registry or load_effect_module_registry()
        selected_pipeline = str(plan.get("selected_pipeline") or "knowledge_card_video")
        template_family = str(plan.get("template_family") or "knowledge_card_motion_case")
        effect_stack = [str(item) for item in (plan.get("effect_stack") or []) if str(item).strip()]
        if not effect_stack:
            effect_stack = _default_modules(selected_pipeline, template_family, registry)
        scene_count = max(3, min(8, len(cinema_scenes or []) or len(_beats(script_body)) or 3))
        has_visual_assets = bool((visual_assets or {}).get("assignments"))
        recipe = {
            "version": "visual_recipe_v1",
            "auto_generated": True,
            "selected_pipeline": selected_pipeline,
            "content_form": str(plan.get("content_form") or selected_pipeline),
            "template_family": template_family,
            "modules": effect_stack[:8],
            "style_variants": _style_variants(cinema_scenes or [], plan, title, script_body),
            "asset_strategy": {
                "primary": "verified_visual_assets" if has_visual_assets else "generated_or_stock_visual_assets",
                "fallback": "html_css_knowledge_card_fallback",
                "forbidden": ["random_unmatched_background", "single_static_background_loop"],
            },
            "selection_reason": _selection_reason(selected_pipeline, template_family, title),
            "differentiation_reason": _differentiation_reason(selected_pipeline, template_family, plan, title),
            "scene_asset_match": _scene_asset_match(scene_count, visual_assets or {}),
            "requires_visual_asset_resolution": not has_visual_assets,
            "avoid": [
                "same_template_as_last_7_days",
                "same_recipe_fingerprint",
                "same_bgm_fingerprint",
                "cross_platform_final_reuse",
            ],
        }
    recipe.setdefault("version", "visual_recipe_v1")
    recipe.setdefault("selected_pipeline", str(plan.get("selected_pipeline") or ""))
    recipe.setdefault("content_form", str(plan.get("content_form") or plan.get("selected_pipeline") or ""))
    recipe.setdefault("template_family", str(plan.get("template_family") or "knowledge_card_motion_case"))
    recipe.setdefault("modules", _default_modules(str(plan.get("selected_pipeline") or ""), str(recipe["template_family"]), registry or load_effect_module_registry()))
    recipe.setdefault("style_variants", _style_variants(cinema_scenes or [], plan, title, script_body))
    recipe.setdefault("asset_strategy", {"primary": "verified_visual_assets", "fallback": "html_css_knowledge_card_fallback", "forbidden": ["random_unmatched_background"]})
    recipe.setdefault("avoid", ["same_recipe_fingerprint", "same_bgm_fingerprint"])
    recipe["scene_manifest"] = _scene_manifest(recipe.get("scene_asset_match") or [], cinema_scenes or [], shotcraft_plan or {})
    recipe["core_fingerprint"] = recipe_core_fingerprint(recipe)
    recipe["fingerprint"] = recipe_instance_fingerprint(recipe)
    return recipe


def validate_visual_recipe(recipe: dict[str, Any] | None, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_effect_module_registry()
    modules_registry = registry.get("modules") if isinstance(registry, dict) else {}
    modules_registry = modules_registry if isinstance(modules_registry, dict) else {}
    failures: list[str] = []
    if not isinstance(recipe, dict) or not recipe:
        return {"passed": False, "failures": ["visual_recipe missing"], "failed_dimensions": ["visual_recipe"]}
    for key in sorted(DEFAULT_REQUIRED_KEYS):
        if recipe.get(key) in (None, "", [], {}):
            failures.append(f"missing {key}")
    modules = recipe.get("modules") if isinstance(recipe.get("modules"), list) else []
    if len(modules) < 3:
        failures.append("modules must include at least 3 entries")
    unknown = [str(item) for item in modules if str(item) not in modules_registry]
    if unknown:
        failures.append("unknown modules: " + ", ".join(unknown[:5]))
    scene_matches = recipe.get("scene_asset_match") if isinstance(recipe.get("scene_asset_match"), list) else []
    if len(scene_matches) < 3:
        failures.append("scene_asset_match must include at least 3 scenes")
    else:
        for index, item in enumerate(scene_matches, 1):
            if not isinstance(item, dict) or not item.get("script_beat") or not item.get("visual_source") or not item.get("match_reason"):
                failures.append(f"scene_asset_match[{index}] incomplete")
                break
    scene_manifest = recipe.get("scene_manifest")
    if scene_manifest is not None:
        manifest = scene_manifest if isinstance(scene_manifest, dict) else {}
        scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
        if manifest.get("source_contract") != "visual_recipe" or len(scenes) != len(scene_matches):
            failures.append("scene_manifest must extend visual_recipe scene_asset_match")
        elif any(not isinstance(scene, dict) or not scene.get("narration") or not scene.get("subtitle") or not scene.get("visual_source") or not scene.get("motion") for scene in scenes):
            failures.append("scene_manifest scenes incomplete")
    style = recipe.get("style_variants") if isinstance(recipe.get("style_variants"), dict) else {}
    if not all(style.get(key) for key in ["color_mood", "motion_density", "text_layout", "scene_change_interval_sec"]):
        failures.append("style_variants must include color_mood, motion_density, text_layout, scene_change_interval_sec")
    asset = recipe.get("asset_strategy") if isinstance(recipe.get("asset_strategy"), dict) else {}
    if not asset.get("primary") or not asset.get("fallback") or "forbidden" not in asset:
        failures.append("asset_strategy must include primary, fallback, and forbidden")
    avoid = set(str(item) for item in (recipe.get("avoid") or []))
    if "same_recipe_fingerprint" not in avoid:
        failures.append("avoid must include same_recipe_fingerprint")
    if "same_bgm_fingerprint" not in avoid:
        failures.append("avoid must include same_bgm_fingerprint")
    return {
        "passed": not failures,
        "failures": failures,
        "failed_dimensions": ["visual_recipe"] if failures else [],
        "module_count": len(modules),
        "core_fingerprint": recipe.get("core_fingerprint") or recipe_core_fingerprint(recipe),
        "fingerprint": recipe.get("fingerprint") or recipe_instance_fingerprint(recipe),
    }


def recipe_core_fingerprint(recipe: dict[str, Any]) -> str:
    style = dict(recipe.get("style_variants") or {})
    if style.get("variant_driven"):
        for key in ["color_mood", "motion_density", "text_layout", "scene_change_interval_sec"]:
            style[key] = "variant_driven"
    style.pop("recipe_variant", None)
    style.pop("variant_driven", None)
    stable = {
        "selected_pipeline": recipe.get("selected_pipeline") or "",
        "content_form": recipe.get("content_form") or "",
        "template_family": recipe.get("template_family"),
        "modules": recipe.get("modules") or [],
        "style_variants": style,
        "asset_strategy": recipe.get("asset_strategy") or {},
    }
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def recipe_instance_fingerprint(recipe: dict[str, Any]) -> str:
    stable = {
        "core_fingerprint": recipe_core_fingerprint(recipe),
        "style_variants": recipe.get("style_variants") or {},
        "scene_asset_match": recipe.get("scene_asset_match") or [],
        "selection_reason": recipe.get("selection_reason") or "",
    }
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def recipe_fingerprint(recipe: dict[str, Any]) -> str:
    """Backward-compatible alias for the per-render recipe identity."""
    return recipe_instance_fingerprint(recipe)


def _default_modules(selected_pipeline: str, template_family: str, registry: dict[str, Any]) -> list[str]:
    family = ((registry.get("template_families") or {}).get(template_family) or {}) if isinstance(registry, dict) else {}
    preferred = [str(item) for item in family.get("default_modules") or [] if str(item).strip()]
    if preferred:
        return preferred
    if selected_pipeline == "localized_repost_video":
        return ["source_video_preserved", "localized_repost_packaging", "lower_third_subtitles", "licensed_bgm_mix"]
    return [
        "template_theme",
        "cinema_color_css",
        "cinema_composition_layout",
        "shotcraft_motion_css",
        "motion_card_layouts",
        "lower_third_subtitles",
        "licensed_bgm_mix",
        "post_render_anti_template_gate",
    ]


def _style_variants(cinema_scenes: list[dict[str, Any]], plan: dict[str, Any], title: str = "", script_body: str = "") -> dict[str, Any]:
    scheme = {}
    for scene in cinema_scenes:
        if isinstance(scene, dict) and isinstance(scene.get("color_scheme"), dict):
            scheme = scene["color_scheme"]
            break
    variant = _recipe_variant(plan, title)
    layouts = ["headline_plus_lower_third", "split_screen_steps", "timeline_cards", "large_number_story", "diagonal_hook_cards"]
    moods = ["content_matched", "warm_editorial", "clean_blueprint", "fresh_green", "high_contrast_note"]
    densities = ["medium", "medium_high", "calm", "fast_cut"]
    index = int(variant[:2], 16) if variant else 0
    return {
        "color_mood": str(scheme.get("mood") or plan.get("color_mood") or moods[index % len(moods)]),
        "motion_density": str(plan.get("motion_density") or densities[index % len(densities)]),
        "text_layout": str(plan.get("text_layout") or layouts[index % len(layouts)]),
        "scene_change_interval_sec": plan.get("scene_change_interval_sec") or (3 + index % 4),
        "semantic_visual_pattern": _semantic_visual_pattern(script_body),
        "recipe_variant": variant,
        "variant_driven": not any(plan.get(key) for key in ["color_mood", "motion_density", "text_layout", "scene_change_interval_sec"]),
    }


def _recipe_variant(plan: dict[str, Any], title: str) -> str:
    """Keep same-template videos distinguishable without binding modules to one channel."""
    identity = {
        "platforms": plan.get("platforms") or [],
        "selected_pipeline": plan.get("selected_pipeline") or "",
        "content_form": plan.get("content_form") or "",
        "template_family": plan.get("template_family") or "",
        "title": title or plan.get("topic") or plan.get("title") or "",
    }
    blob = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def _semantic_visual_pattern(script_body: str) -> str:
    beats = _beats(script_body)
    if not beats:
        return "strategy_default"
    normalized = "|".join(" ".join(beat.casefold().split())[:120] for beat in beats[:8])
    blob = json.dumps({"beat_count": len(beats), "beats": normalized}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def _scene_asset_match(count: int, visual_assets: dict[str, Any]) -> list[dict[str, Any]]:
    assignments = list((visual_assets or {}).get("assignments") or [])
    rows = []
    for index in range(max(3, count)):
        item = assignments[index % len(assignments)] if assignments else {}
        rows.append(
            {
                "scene": index + 1,
                "script_beat": str(item.get("script_beat") or item.get("purpose") or f"beat-{index + 1}"),
                "visual_source": str(item.get("background_image") or item.get("image") or item.get("source") or f"planned_generated_or_stock_asset:beat-{index + 1}"),
                "match_reason": str(item.get("match_reason") or item.get("purpose") or f"visual asset must be resolved to match beat-{index + 1} before final publishing"),
            }
        )
    return rows


def _scene_manifest(scene_matches: list[dict[str, Any]], cinema_scenes: list[dict[str, Any]], shotcraft_plan: dict[str, Any]) -> dict[str, Any]:
    timeline = shotcraft_plan.get("timeline") if isinstance(shotcraft_plan, dict) else []
    timeline = timeline if isinstance(timeline, list) else []
    scenes = []
    for index, match in enumerate(scene_matches, 1):
        motion = timeline[(index - 1) % len(timeline)] if timeline else {}
        cinema = cinema_scenes[(index - 1) % len(cinema_scenes)] if cinema_scenes else {}
        scenes.append({
            "scene": index,
            "narration": str(match.get("script_beat") or ""),
            "subtitle": str(match.get("script_beat") or ""),
            "visual_source": str(match.get("visual_source") or ""),
            "asset_match_reason": str(match.get("match_reason") or ""),
            "motion": str((motion or {}).get("name") or (motion or {}).get("move_id") or (cinema or {}).get("motion") or "planned_scene_motion"),
        })
    return {"version": "scene_manifest_v1", "source_contract": "visual_recipe", "scenes": scenes}


def _selection_reason(selected_pipeline: str, template_family: str, title: str) -> str:
    return f"{template_family} selected as a starting visual family for {selected_pipeline}; modules are combined per topic rather than fixed per platform. {title[:80]}".strip()


def _differentiation_reason(selected_pipeline: str, template_family: str, plan: dict[str, Any], title: str) -> str:
    platforms = ",".join(str(item) for item in (plan.get("platforms") or [])) or "unspecified-platform"
    form = str(plan.get("content_form") or selected_pipeline)
    variant = _recipe_variant(plan, title)
    return (
        f"{template_family} is varied for {platforms}/{form}: module stack, text layout, color mood, "
        f"scene rhythm, and resolved assets must differ from recent renders; variant={variant}"
    )


def _beats(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").replace("\r", "\n").split("\n") if part.strip()]
