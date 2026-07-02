SHORT_VIDEO_PLATFORMS = {"douyin", "tiktok", "youtube", "bilibili", "kuaishou"}
NOTE_PLATFORMS = {"xiaohongshu", "rednote", "instagram", "threads"}
ARTICLE_PLATFORMS = {"wechat", "weixin", "devto", "linkedin", "telegraph", "mataroa", "tabnews"}


def choose_content_strategy(topic, brief, viral_score, niche_report):
    brief = brief or {}
    viral_score = viral_score or {"dimensions": {}, "total_score": 0.0}
    niche_report = niche_report or {}
    requested = [str(item).casefold() for item in brief.get("platforms", [])]
    primary_platforms = requested or list(niche_report.get("platform_distribution", {}).keys())[:2] or ["wechat"]
    visual = float(viral_score.get("dimensions", {}).get("visual_promise", 0.5))
    if any(platform in SHORT_VIDEO_PLATFORMS for platform in primary_platforms) and visual >= 0.75:
        content_form = "short_video"
        asset_plan = ["script", "cover", "audio", "video"]
    elif any(platform in NOTE_PLATFORMS for platform in primary_platforms):
        content_form = "social_note"
        asset_plan = ["cover", "content_images", "caption"]
    elif visual >= 0.7:
        content_form = "image_carousel"
        asset_plan = ["cover", "content_images", "caption"]
    else:
        content_form = "long_article"
        asset_plan = ["cover", "article"]
    return {
        "topic": topic,
        "content_form": content_form,
        "primary_platforms": primary_platforms,
        "asset_plan": asset_plan,
        "reason": {
            "score": viral_score.get("total_score", 0.0),
            "trend_stage": viral_score.get("trend_stage", "emerging"),
            "style_formats": niche_report.get("style_signature", {}).get("formats", []),
        },
    }
