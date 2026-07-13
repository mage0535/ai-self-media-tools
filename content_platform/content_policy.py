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
    "devto",
    "facebook",
    "instagram",
    "linkedin",
    "mastodon",
    "mataroa",
    "pinterest",
    "reddit",
    "tabnews",
    "telegraph",
    "threads",
    "tiktok",
    "twitter",
    "x",
    "youtube",
}

SHORT_VIDEO_PLATFORMS = {"bilibili", "douyin", "kuaishou", "shipinhao", "tiktok", "youtube"}


def normalize_platform(platform):
    return str(platform or "").strip().lower()


def platform_region(platform):
    normalized = normalize_platform(platform)
    if normalized in DOMESTIC_PLATFORMS:
        return "domestic"
    if normalized in INTERNATIONAL_PLATFORMS:
        return "international"
    return "unknown"


def is_short_video_platform(platform):
    return normalize_platform(platform) in SHORT_VIDEO_PLATFORMS


def generated_media_kinds_for_job(job, config):
    """Return locally generated media kinds allowed by the fixed content strategy."""
    policy = (config or {}).get("content_policy", {})
    media_cfg = (config or {}).get("media", {})
    kinds = []
    if media_cfg.get("image", {}).get("enabled", False):
        kinds.append("image")

    allow_video = bool(policy.get("allow_local_video_generation", False))
    allow_audio = bool(policy.get("allow_local_audio_generation", False))
    if allow_video and media_cfg.get("video", {}).get("enabled", False):
        kinds.append("video")
    if allow_audio and media_cfg.get("audio", {}).get("enabled", False):
        kinds.append("audio")
    return tuple(kinds)


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
        intl = routing_defaults.get("international", {})
        return {
            "type": "aitoearn-draft",
            "base_url": intl.get("base_url", "https://aitoearn.ai/api/unified/mcp"),
            "api_key_env": intl.get("api_key_env", "AITOEARN_INTL_API_KEY"),
            **{k: v for k, v in intl.items() if k not in {"base_url", "api_key_env"}},
        }
    return None
