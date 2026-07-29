DOMESTIC_PLATFORMS = {
    "baijiahao",
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

SHORT_VIDEO_PLATFORMS = {"bilibili", "douyin", "kuaishou", "shipinhao", "tiktok", "youtube"}
XIAOHONGSHU_PLATFORMS = {"xiaohongshu", "rednote"}
DOUYIN_PLATFORMS = {"douyin"}
MANUAL_HANDOFF_PLATFORMS = {"douyin", "shipinhao", "xiaohongshu", "rednote"}


def normalize_platform(platform):
    return str(platform or "").strip().lower()


def platform_region(platform):
    normalized = normalize_platform(platform)
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


def is_douyin_platform(platform):
    return normalize_platform(platform) in DOUYIN_PLATFORMS


def is_manual_handoff_platform(platform):
    return normalize_platform(platform) in MANUAL_HANDOFF_PLATFORMS


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
            "type": "aitoearn-intl",
            "platform_name": international.get("platform_name", platform),
            "account_name": international.get("account_name", "default"),
            **{k: v for k, v in international.items() if k != "platform_name"},
        }
    return None
