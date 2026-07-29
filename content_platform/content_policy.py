DOMESTIC_PLATFORMS = {
    "bilibili",
    "douyin",
    "juejin",
    "kuaishou",
    "shipinhao",
    "wechat",
    "xiaohongshu",
    "zhihu",
}

INTERNATIONAL_PLATFORMS = {
    "bluesky",
    "buttondown",
    "devto",
    "mastodon",
    "nostr",
    "telegraph",
    "threads",
    "tiktok",
    "twitter",
    "writeas",
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
    # Handle mastodon instances (mastodon_mstdn_social → mastodon)
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


def xiaohongshu_recovery_policy():
    return {
        "mode": "manual_handoff_only",
        "reason": "Hermes generates image-text, knowledge-card, and short-video review packages; user publishes manually",
        "required_gates": [
            "ai_assisted_disclosure",
            "authentic_source_evidence",
            "non_template_copy",
            "human_review",
        ],
    }



def generated_media_kinds_for_job(job, config):
    """Return media kinds needed for a job based on platforms and content form."""
    platforms = job.get("platforms", [])
    kinds = set()
    for platform in platforms:
        if platform in SHORT_VIDEO_PLATFORMS:
            kinds.add("video")
        elif platform in ("wechat", "weixin", "wechat_official"):
            kinds.add("image")
        elif platform in ("zhihu", "juejin"):
            kinds.add("image")
        elif platform in ("xiaohongshu", "rednote"):
            kinds.add("image")
    # Always add cover if not already present
    if "image" in kinds:
        kinds.add("cover")
    return list(kinds)




def platform_strategy_policy(platform):
    """Return strategy policy name for a platform."""
    platform = normalize_platform(platform)
    if platform in ("douyin", "kuaishou", "shipinhao", "bilibili", "tiktok", "youtube"):
        return "short_video"
    if platform in ("wechat", "weixin", "wechat_official", "zhihu", "juejin", "devto", "xiaohongshu"):
        return "article"
    if platform in ("twitter", "x", "threads", "bluesky", "mastodon", "nostr"):
        return "short_text"
    return "general"


def generated_media_kinds_for_job(job, config):
    """Return media kinds needed for a job based on platforms and content form."""
    platforms = job.get("platforms", [])
    kinds = set()
    for platform in platforms:
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
        intl = routing_defaults.get("international", {})
        return {
            "type": "aitoearn-draft",
            "base_url": intl.get("base_url", "https://aitoearn.ai/api/unified/mcp"),
            "api_key_env": intl.get("api_key_env", "AITOEARN_INTL_API_KEY"),
            **{k: v for k, v in intl.items() if k not in {"base_url", "api_key_env"}},
        }
    return None
