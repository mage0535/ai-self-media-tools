from .content_policy import SHORT_VIDEO_PLATFORMS
from .video_toolchain import build_video_toolchain_plan

NOTE_PLATFORMS = {"xiaohongshu", "rednote", "instagram", "threads"}
ARTICLE_PLATFORMS = {"wechat", "weixin", "devto", "telegraph", "mataroa", "tabnews"}
EXPLAINER_VIDEO_PLATFORMS = {"youtube", "bilibili", "kuaishou"}


def choose_content_strategy(topic, brief, viral_score, niche_report, viral_growth_report=None):
    brief = brief or {}
    viral_score = viral_score or {"dimensions": {}, "total_score": 0.0}
    niche_report = niche_report or {}
    viral_growth_report = viral_growth_report or {}
    requested = [str(item).casefold() for item in brief.get("platforms", [])]
    primary_platforms = requested or list(niche_report.get("platform_distribution", {}).keys())[:2] or ["wechat"]
    secondary_platforms = [platform for platform in niche_report.get("platform_distribution", {}) if platform not in primary_platforms][:3]
    visual = float(viral_score.get("dimensions", {}).get("visual_promise", 0.5))
    utility = float(viral_score.get("dimensions", {}).get("utility", 0.5))
    recommendation = str(viral_score.get("recommendation", "test"))
    explicit_form = str(brief.get("content_form") or brief.get("preferred_content_form") or "").casefold()
    line = " ".join(str(brief.get(key, "")) for key in ("content_line", "video_line", "topic", "intent")).casefold()
    forms = {str(item).casefold() for item in (niche_report.get("style_signature", {}) or {}).get("formats", [])}
    viral_forms = {
        signal
        for item in viral_growth_report.get("topic_ammo", [])
        for signal in str(item.get("title", "")).casefold().split()
    }
    wants_repost = bool(brief.get("source_video") or brief.get("source_video_path") or brief.get("source_url")) or any(token in line for token in ("repost", "搬运", "二创", "remix"))
    wants_explainer = (
        explicit_form in {"article_explainer_video", "knowledge_video", "tutorial_video"}
        or bool(brief.get("article_to_video") or brief.get("knowledge_video"))
        or (
            any(platform in EXPLAINER_VIDEO_PLATFORMS for platform in primary_platforms)
            and not wants_repost
            and (utility >= 0.72 or forms.intersection({"tutorial", "case_study", "listicle"}) or viral_forms.intersection({"guide", "tutorial", "workflow", "方法", "教程"}))
        )
    )
    if wants_explainer:
        content_form = "article_explainer_video"
        asset_plan = ["article", "knowledge_cards", "content_images", "human_voiceover", "background_music", "caption"]
    elif any(platform in SHORT_VIDEO_PLATFORMS for platform in primary_platforms) and visual >= 0.75:
        content_form = "short_video"
        asset_plan = ["source_video", "cover", "caption"]
    elif any(platform in NOTE_PLATFORMS for platform in primary_platforms):
        content_form = "social_note"
        asset_plan = ["cover", "content_images", "caption"]
    elif visual >= 0.7:
        content_form = "image_carousel"
        asset_plan = ["cover", "content_images", "caption"]
    elif utility >= 0.72:
        content_form = "checklist_article"
        asset_plan = ["cover", "article", "caption"]
    else:
        content_form = "long_article"
        asset_plan = ["cover", "article"]
    warnings = []
    if recommendation == "hold":
        warnings.append("topic score is below publish threshold; gather more references before scaling")
    if not niche_report.get("account_count", 0):
        warnings.append("same-track account evidence is thin")
    if content_form == "short_video":
        warnings.append("short video strategy requires an existing source video; local video generation is disabled by default")
    if content_form == "article_explainer_video":
        warnings.append("article explainer video requires article draft, section images, voiceover, real-instrument BGM, subtitles, and renderer manifest")
    video_toolchain_plan = build_video_toolchain_plan(
        {
            "content_form": content_form,
            "primary_platforms": primary_platforms,
            "asset_plan": asset_plan,
        },
        brief,
    )
    return {
        "topic": topic,
        "content_form": content_form,
        "primary_platforms": primary_platforms,
        "secondary_platforms": secondary_platforms,
        "asset_plan": asset_plan,
        "video_toolchain_plan": video_toolchain_plan,
        "recommended_next_step": recommendation,
        "confidence": round((viral_score.get("total_score", 0.0) + utility + visual) / 3, 3),
        "warnings": warnings,
        "reason": {
            "score": viral_score.get("total_score", 0.0),
            "trend_stage": viral_score.get("trend_stage", "emerging"),
            "style_formats": niche_report.get("style_signature", {}).get("formats", []),
            "viral_growth_candidates": len(viral_growth_report.get("viral_candidates", [])),
        },
    }
