DOMESTIC_PLATFORMS = {
    "bilibili",
    "csdn",
    "douyin",
    "juejin",
    "kuaishou",
    "rednote",
    "shipinhao",
    "toutiao",
    "wechat",
    "wechat_official",
    "weibo",
    "weixin",
    "xiaohongshu",
    "zhihu",
}

INTERNATIONAL_PLATFORMS = {
    "bluesky",
    "buttondown",
    "devto",
    "facebook",
    "instagram",
    "linkedin",
    "mastodon",
    "mataroa",
    "nostr",
    "pinterest",
    "reddit",
    "tabnews",
    "telegraph",
    "threads",
    "tiktok",
    "twitter",
    "writeas",
    "x",
    "youtube",
}

DOUYIN_ACCOUNT_VARIANTS = {"douyin_pet", "douyin_ai"}
SHORT_VIDEO_PLATFORMS = {"bilibili", "douyin", "kuaishou", "shipinhao", "tiktok", "youtube", *DOUYIN_ACCOUNT_VARIANTS}
XIAOHONGSHU_PLATFORMS = {"xiaohongshu", "rednote"}
# Only these channels may use an automatic delivery publisher.  This is a
# fail-closed allowlist: adding a platform elsewhere must not silently enable
# upload or scheduling for it.
AUTOMATED_DELIVERY_PLATFORMS = frozenset({
    "kuaishou",
    "zhihu",
    "juejin",
    "wechat",
    "wechat_official",
    "weixin",
    "twitter",
    "x",
})
# Preserve the old name for callers that only need to ask whether an
# automated route is permitted.  The detailed mode below distinguishes draft,
# scheduled, and direct publication.
AUTO_PUBLISH_PLATFORMS = AUTOMATED_DELIVERY_PLATFORMS
DELIVERY_MODES = {
    "kuaishou": "automatic_scheduled",
    "zhihu": "draft_box",
    "juejin": "draft_box",
    "wechat": "draft_box",
    "wechat_official": "draft_box",
    "weixin": "draft_box",
    "twitter": "direct_publish",
    "x": "direct_publish",
}
# This is intentionally separate from the broader manual-handoff set.  The
# account recovery policy makes Xiaohongshu a permanent fail-closed boundary:
# config, routing defaults, and health data must never re-enable an uploader.
STRICT_MANUAL_HANDOFF_PLATFORMS = frozenset(XIAOHONGSHU_PLATFORMS)
DOUYIN_PLATFORMS = {"douyin", *DOUYIN_ACCOUNT_VARIANTS}
MANUAL_HANDOFF_PLATFORMS = frozenset({
    "bilibili",
    "douyin",
    "douyin_ai",
    "douyin_pet",
    "shipinhao",
    "tiktok",
    "youtube",
    "xiaohongshu",
    "rednote",
})


def normalize_platform(platform):
    return str(platform or "").strip().lower()


def platform_region(platform):
    normalized = normalize_platform(platform)
    if normalized in DOUYIN_ACCOUNT_VARIANTS:
        return "domestic"
    if normalized in DOMESTIC_PLATFORMS:
        return "domestic"
    if normalized in INTERNATIONAL_PLATFORMS:
        return "international"
    if normalized.startswith("mastodon_"):
        return "international"
    return "unknown"


def is_short_video_platform(platform):
    return normalize_platform(platform) in SHORT_VIDEO_PLATFORMS


def is_xiaohongshu_platform(platform):
    return normalize_platform(platform) in XIAOHONGSHU_PLATFORMS


def is_strict_manual_handoff_platform(platform):
    return normalize_platform(platform) in STRICT_MANUAL_HANDOFF_PLATFORMS


def is_douyin_platform(platform):
    return normalize_platform(platform) in DOUYIN_PLATFORMS


def is_manual_handoff_platform(platform):
    return normalize_platform(platform) in MANUAL_HANDOFF_PLATFORMS


def is_auto_publish_platform(platform):
    """Return whether the platform is explicitly allowed to auto-deliver."""
    return normalize_platform(platform) in AUTO_PUBLISH_PLATFORMS


def delivery_mode(platform):
    """Return the immutable delivery boundary used by production workflows."""
    normalized = normalize_platform(platform)
    if normalized in DELIVERY_MODES:
        return DELIVERY_MODES[normalized]
    if normalized in MANUAL_HANDOFF_PLATFORMS:
        return "manual_handoff"
    return "unsupported"


def generated_media_kinds_for_job(job, config):
    """Return locally generated media kinds allowed by the fixed content strategy."""
    policy = (config or {}).get("content_policy", {})
    media_cfg = (config or {}).get("media", {})
    platforms = [normalize_platform(p) for p in (job or {}).get("platforms", [])]
    kinds = set()
    if media_cfg.get("image", {}).get("enabled", False):
        kinds.add("image")
    if media_cfg.get("cover", {}).get("enabled", False):
        kinds.add("cover")

    allow_video = bool(policy.get("allow_local_video_generation", False))
    allow_audio = bool(policy.get("allow_local_audio_generation", False))
    if allow_video and media_cfg.get("video", {}).get("enabled", False):
        for platform in platforms:
            if platform in SHORT_VIDEO_PLATFORMS:
                kinds.add("video")
                break
    if allow_audio and media_cfg.get("audio", {}).get("enabled", False):
        kinds.add("audio")
    return tuple(sorted(kinds))


def recommended_media_kinds(platforms):
    kinds = set()
    for platform in [normalize_platform(p) for p in platforms]:
        if platform in SHORT_VIDEO_PLATFORMS:
            kinds.add("video")
        elif platform in ("wechat", "weixin", "wechat_official", "zhihu", "juejin", "xiaohongshu", "rednote"):
            kinds.add("image")
    if "image" in kinds:
        kinds.add("cover")
    return list(kinds)


def default_publisher_config(platform, routing_defaults):
    if not routing_defaults.get("enabled", False):
        return None
    region = platform_region(platform)
    if region == "domestic":
        domestic = routing_defaults.get("domestic", {})
        return {
            "type": "social-auto-upload",
            "platform_name": domestic.get("platform_name", platform),
            "account_name": domestic.get("account_name", "default"),
            **{k: v for k, v in domestic.items() if k != "platform_name"},
        }
    if region == "international":
        international = routing_defaults.get("international", {})
        return {
            "type": international.get("type", "manual-handoff"),
            "platform_name": international.get("platform_name", platform),
            "account_name": international.get("account_name", "default"),
            **{k: v for k, v in international.items() if k != "platform_name"},
        }
    return None
