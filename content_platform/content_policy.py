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
DELIVERY_MODES = {
    "kuaishou": "automatic_scheduled",
    "zhihu": "draft_box",
    "juejin": "draft_box",
    "wechat": "draft_box",
    "wechat_official": "draft_box",
    "weixin": "draft_box",
    "twitter": "direct_publish",
    "x": "direct_publish",
    "bilibili": "manual_handoff",
    "douyin": "manual_handoff",
    "douyin_ai": "manual_handoff",
    "douyin_pet": "manual_handoff",
    "shipinhao": "manual_handoff",
    "tiktok": "manual_handoff",
    "youtube": "manual_handoff",
    "xiaohongshu": "manual_handoff",
    "rednote": "manual_handoff",
}
DELIVERY_PUBLISHER_TYPES = {
    "kuaishou": "social-auto-upload",
    "zhihu": "zhihu-playwright",
    "juejin": "juejin-api",
    "wechat": "wechat-draft",
    "wechat_official": "wechat-draft",
    "weixin": "wechat-draft",
    "twitter": "x-playwright",
    "x": "x-playwright",
    **{
        platform: "manual-handoff"
        for platform in (
            "bilibili", "douyin", "douyin_ai", "douyin_pet", "shipinhao",
            "tiktok", "youtube", "xiaohongshu", "rednote",
        )
    },
}
# These sets are derived compatibility views. DELIVERY_MODES is the canonical
# source and unknown platforms remain unsupported.
AUTOMATED_DELIVERY_PLATFORMS = frozenset(
    platform for platform, mode in DELIVERY_MODES.items() if mode != "manual_handoff"
)
AUTO_PUBLISH_PLATFORMS = AUTOMATED_DELIVERY_PLATFORMS
# This is intentionally separate from the broader manual-handoff set.  The
# account recovery policy makes Xiaohongshu a permanent fail-closed boundary:
# config, routing defaults, and health data must never re-enable an uploader.
STRICT_MANUAL_HANDOFF_PLATFORMS = frozenset(XIAOHONGSHU_PLATFORMS)
DOUYIN_PLATFORMS = {"douyin", *DOUYIN_ACCOUNT_VARIANTS}
MANUAL_HANDOFF_PLATFORMS = frozenset(
    platform for platform, mode in DELIVERY_MODES.items() if mode == "manual_handoff"
)


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
    return DELIVERY_MODES.get(normalize_platform(platform), "unsupported")


def validate_delivery_policy_config(config):
    """Validate mutable publisher configuration against the immutable matrix."""
    publishers = (config or {}).get("publishers")
    if not isinstance(publishers, dict):
        return {"passed": False, "failures": ["publishers_config_missing"]}
    failures = []
    defaults = publishers.get("routing_defaults") if isinstance(publishers.get("routing_defaults"), dict) else {}
    for region in ("domestic", "international"):
        route = defaults.get(region) if isinstance(defaults.get(region), dict) else {}
        if route and str(route.get("type") or "manual-handoff") != "manual-handoff":
            failures.append(f"routing_default_must_fail_closed:{region}")
    platforms = publishers.get("platforms") if isinstance(publishers.get("platforms"), dict) else {}
    for platform, expected_type in DELIVERY_PUBLISHER_TYPES.items():
        entry = platforms.get(platform)
        if not isinstance(entry, dict):
            failures.append(f"publisher_route_missing:{platform}")
            continue
        actual = str(entry.get("type") or "")
        if actual != expected_type:
            failures.append(f"publisher_route_mismatch:{platform}:{actual or 'missing'}:{expected_type}")
        if platform in {"zhihu", "juejin"} and entry.get("save_as_draft") is False:
            failures.append(f"draft_route_cannot_publish:{platform}")
    return {"passed": not failures, "failures": failures}


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
    # The video renderer owns narration, subtitles, BGM, and the final audio
    # stream. A second audio pass would overwrite its measured TTS sidecars.
    if "video" not in kinds and allow_audio and media_cfg.get("audio", {}).get("enabled", False):
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
    normalized = normalize_platform(platform)
    mode = delivery_mode(normalized)
    region = platform_region(platform)
    defaults = routing_defaults.get(region, {}) if region in {"domestic", "international"} else {}
    shared = {k: v for k, v in defaults.items() if k not in {"type", "platform_name"}}
    route_types = {
        "kuaishou": "social-auto-upload",
        "wechat": "wechat-draft",
        "weixin": "wechat-draft",
        "wechat_official": "wechat-draft",
        "zhihu": "zhihu-playwright",
        "juejin": "juejin-api",
        "twitter": "x-playwright",
        "x": "x-playwright",
    }
    if mode == "manual_handoff":
        return {"type": "manual-handoff", "reason": defaults.get("reason", "manual publish required by delivery policy")}
    if normalized not in route_types:
        return None
    return {
        **shared,
        "type": route_types[normalized],
        "platform_name": defaults.get("platform_name", normalized),
        "account_name": defaults.get("account_name", "default"),
    }
