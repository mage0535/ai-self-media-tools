from .content_policy import SHORT_VIDEO_PLATFORMS

NOTE_PLATFORMS = {"xiaohongshu", "rednote", "instagram", "threads"}
ARTICLE_PLATFORMS = {"wechat", "weixin", "devto", "linkedin", "telegraph", "mataroa", "tabnews"}


def choose_content_strategy(topic, brief, viral_score, niche_report):
    brief = brief or {}
    viral_score = viral_score or {"dimensions": {}, "total_score": 0.0}
    niche_report = niche_report or {}
    requested = [str(item).casefold() for item in brief.get("platforms", [])]
    primary_platforms = requested or list(niche_report.get("platform_distribution", {}).keys())[:2] or ["wechat"]
    secondary_platforms = [platform for platform in niche_report.get("platform_distribution", {}) if platform not in primary_platforms][:3]
    visual = float(viral_score.get("dimensions", {}).get("visual_promise", 0.5))
    utility = float(viral_score.get("dimensions", {}).get("utility", 0.5))
    recommendation = str(viral_score.get("recommendation", "test"))
    if any(platform in SHORT_VIDEO_PLATFORMS for platform in primary_platforms) and visual >= 0.75:
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
    return {
        "topic": topic,
        "content_form": content_form,
        "primary_platforms": primary_platforms,
        "secondary_platforms": secondary_platforms,
        "asset_plan": asset_plan,
        "recommended_next_step": recommendation,
        "confidence": round((viral_score.get("total_score", 0.0) + utility + visual) / 3, 3),
        "warnings": warnings,
        "reason": {
            "score": viral_score.get("total_score", 0.0),
            "trend_stage": viral_score.get("trend_stage", "emerging"),
            "style_formats": niche_report.get("style_signature", {}).get("formats", []),
        },
    }
