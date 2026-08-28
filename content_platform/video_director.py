"""Single deterministic authority for content- and platform-driven video routing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


PLATFORM_PROFILES = {
    "kuaishou": "fast_practical",
    "douyin": "high_retention",
    "douyin_ai": "high_retention",
    "douyin_pet": "playful_documentary",
    "shipinhao": "trust_microcase",
    "xiaohongshu": "saveable_editorial",
    "bilibili": "deep_explainer",
    "youtube": "global_explainer",
    "tiktok": "fast_global",
}

SCENE_MIXES = {
    "real_footage_story": ["hero_footage", "behavior_closeup", "context_wide", "evidence_overlay", "reaction_cut", "process_insert", "result_reveal", "cta_footage"],
    "screen_demo": ["hero_poster", "ui_focus", "cursor_demo", "split_screen", "process_flow", "evidence_zoom", "result_overlay", "cta"],
    "split_comparison": ["hero_conflict", "split_screen", "side_a", "side_b", "difference_grid", "evidence_zoom", "winner_reveal", "cta"],
    "data_story": ["hero_number", "chart_build", "metric_focus", "timeline", "comparison", "evidence_source", "takeaway_grid", "cta"],
    "layered_checklist": ["hero_poster", "list_reveal", "timeline", "diagram", "real_asset_overlay", "card_stack", "summary_grid", "cta"],
    "cinematic_explainer": ["hero_poster", "establishing", "detail_closeup", "process_flow", "split_screen", "evidence_zoom", "payoff_reveal", "cta"],
}


def build_video_route(
    *, platform: str, title: str, body: str, content_form: str,
    available_assets: dict[str, Any] | None = None, recent_style_ids: list[str] | None = None,
) -> dict[str, Any]:
    platform = str(platform or "").casefold()
    text = f"{title} {body}".casefold()
    assets = available_assets or {}
    modality = _modality(text, int(assets.get("footage_count") or 0), content_form)
    renderer_id = _renderer(platform, modality)
    palettes = _palettes(platform, modality)
    typography = ["editorial_condensed", "bold_geometric", "documentary_sans"]
    recent = set(str(item) for item in (recent_style_ids or []))
    selected = None
    for palette in palettes:
        for type_style in typography:
            candidate = f"{platform}:{renderer_id}:{modality}:{palette}:{type_style}"
            if candidate not in recent:
                selected = (candidate, palette, type_style)
                break
        if selected:
            break
    selected = selected or (f"{platform}:{renderer_id}:{modality}:{palettes[0]}:{typography[0]}", palettes[0], typography[0])
    style_id, palette, type_style = selected
    presentations = list(SCENE_MIXES[modality])
    route = {
        "version": "video_route_decision_v2",
        "platform": platform,
        "platform_profile": PLATFORM_PROFILES.get(platform, "editorial_video"),
        "pipeline_id": _pipeline(renderer_id, modality),
        "renderer_id": renderer_id,
        "template_family": modality,
        "presentation_mode": modality,
        "style_id": style_id,
        "palette_id": palette,
        "typography_id": type_style,
        "scene_presentations": presentations,
        "required_assets": _required_assets(renderer_id, modality),
        "modules": _modules(modality),
        "history_window_days": 3,
        "selection_reason": f"{modality} matches {platform or 'video'} content signals and verified asset availability",
    }
    route["fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(route, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return route


def _modality(text: str, footage_count: int, content_form: str) -> str:
    if footage_count >= 8:
        return "real_footage_story"
    if any(token in text for token in ("vs", "versus", "对比", "区别", "a平台", "b平台", "before", "after")):
        return "split_comparison"
    if any(token in text for token in ("数据", "指标", "%", "增长", "下降", "chart", "metric")):
        return "data_story"
    if any(token in text for token in ("界面", "截图", "api", "操作", "演示", "demo", "screen")):
        return "screen_demo"
    if any(token in text for token in ("第一步", "第二步", "清单", "步骤", "避坑", "checklist")):
        return "layered_checklist"
    return "cinematic_explainer"


def _renderer(platform: str, modality: str) -> str:
    if modality == "real_footage_story":
        return "real_footage_renderer"
    if platform in {"bilibili", "youtube"}:
        return "landscape_explainer_renderer"
    if modality == "layered_checklist":
        return "layered_card_renderer"
    return "cinema_multishot_renderer"


def _pipeline(renderer_id: str, modality: str) -> str:
    return {
        "real_footage_renderer": "real_footage_overlay_video",
        "landscape_explainer_renderer": "landscape_explainer_video",
        "layered_card_renderer": "layered_knowledge_card_video",
        "cinema_multishot_renderer": f"{modality}_cinematic_video",
    }[renderer_id]


def _required_assets(renderer_id: str, modality: str) -> list[str]:
    if renderer_id == "real_footage_renderer":
        return ["eight_verified_footage_clips", "scene_manifest", "tts", "online_bgm"]
    if modality == "screen_demo":
        return ["verified_screenshots_or_ui_assets", "scene_manifest", "tts", "online_bgm"]
    return ["eight_unique_semantic_visuals", "scene_manifest", "tts", "online_bgm"]


def _modules(modality: str) -> list[str]:
    common = ["cinema_composition_layout", "shotcraft_motion_css", "lower_third_subtitles", "licensed_bgm_mix"]
    specific = {
        "real_footage_story": ["source_video_preserved", "semantic_transition"],
        "screen_demo": ["screencast_template", "evidence_interface_overlay"],
        "split_comparison": ["split_screen_compositor", "comparison_labels"],
        "data_story": ["data_visualization", "number_motion"],
        "layered_checklist": ["knowledge_card_designer", "motion_card_layouts"],
        "cinematic_explainer": ["visual_asset_assignments", "cinema_color_css"],
    }
    return specific[modality] + common


def _palettes(platform: str, modality: str) -> list[str]:
    if platform == "douyin_pet":
        return ["sunlit_playful", "warm_documentary", "fresh_story"]
    if platform in {"bilibili", "youtube"}:
        return ["studio_blue", "editorial_warm", "evidence_dark"]
    if modality in {"screen_demo", "data_story"}:
        return ["evidence_dark", "clean_blueprint", "high_contrast_note"]
    return ["cinematic_amber", "clean_blueprint", "editorial_warm"]
