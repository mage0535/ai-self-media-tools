PLATFORM_CATALOG = {
    "wechat": {
        "key": "wechat",
        "label": "微信公众号",
        "group": "china",
        "auth_modes": ["manual", "env", "app_credentials"],
        "supports": ["article", "draft", "image"],
        "binding_steps": [
            "准备微信公众号 AppID 与 AppSecret。",
            "确认封面图生成脚本或上传素材可用。",
            "在管理页中填写账号名称、认证方式和凭据引用位置。",
            "完成后执行账号检测并确认状态为 connected。",
        ],
    },
    "xiaohongshu": {
        "key": "xiaohongshu",
        "label": "小红书",
        "group": "china",
        "auth_modes": ["manual", "cookie", "social-auto-upload"],
        "supports": ["note", "image", "draft"],
        "binding_steps": [
            "准备 cookie 或 social-auto-upload 账号环境。",
            "在管理页中选择认证方式并填写凭据引用位置。",
            "确认图片产物脚本可生成封面和内容图。",
            "执行账号检测并查看是否能进入 draft 流程。",
        ],
    },
    "douyin": {
        "key": "douyin",
        "label": "抖音",
        "group": "china",
        "auth_modes": ["manual", "cookie", "social-auto-upload"],
        "supports": ["video", "audio", "draft"],
        "binding_steps": [
            "准备浏览器会话或 social-auto-upload 账号。",
            "确认视频脚本、音频和视频产物链可运行。",
            "填写账号信息后执行检测。",
            "通过后即可用于短视频草稿分发。",
        ],
    },
    "bilibili": {
        "key": "bilibili",
        "label": "Bilibili",
        "group": "china",
        "auth_modes": ["manual", "cookie"],
        "supports": ["article", "video", "draft"],
        "binding_steps": [
            "准备 SESSDATA 与 bili_jct 或浏览器会话。",
            "填写凭据引用位置并确认文章或视频模式。",
            "执行检测并查看是否返回 connected。",
        ],
    },
    "youtube": {
        "key": "youtube",
        "label": "YouTube",
        "group": "global",
        "auth_modes": ["manual", "oauth_env"],
        "supports": ["video", "draft", "publish"],
        "binding_steps": [
            "准备 OAuth client_id、client_secret、refresh_token。",
            "确认视频脚本与产物输出可用。",
            "填写账号信息并执行检测。",
        ],
    },
    "linkedin": {
        "key": "linkedin",
        "label": "LinkedIn",
        "group": "global",
        "auth_modes": ["manual", "access_token"],
        "supports": ["article", "post", "publish"],
        "binding_steps": [
            "准备 access token 与可选 organization id。",
            "填写账号名称和认证信息。",
            "执行检测并确认可发布状态。",
        ],
    },
    "devto": {
        "key": "devto",
        "label": "Dev.to",
        "group": "global",
        "auth_modes": ["manual", "api_key"],
        "supports": ["article", "draft"],
        "binding_steps": [
            "准备 DEVTO API Key。",
            "填写账号信息后执行检测。",
            "确认 draft 输出和 markdown 格式符合预期。",
        ],
    },
    "telegraph": {
        "key": "telegraph",
        "label": "Telegraph",
        "group": "global",
        "auth_modes": ["manual", "token"],
        "supports": ["article", "publish"],
        "binding_steps": [
            "准备 Telegraph token。",
            "确认是否允许 live publishing。",
            "填写账号信息并执行检测。",
        ],
    },
    "mastodon": {
        "key": "mastodon",
        "label": "Mastodon",
        "group": "global",
        "auth_modes": ["manual", "access_token"],
        "supports": ["post", "publish"],
        "binding_steps": [
            "准备实例地址与 access token。",
            "填写账号信息并执行检测。",
        ],
    },
    "bluesky": {
        "key": "bluesky",
        "label": "Bluesky",
        "group": "global",
        "auth_modes": ["manual", "username_password"],
        "supports": ["post", "publish"],
        "binding_steps": [
            "准备 identifier 与 password。",
            "填写账号信息并执行检测。",
        ],
    },
    "reddit": {
        "key": "reddit",
        "label": "Reddit",
        "group": "global",
        "auth_modes": ["manual_review", "oauth_env"],
        "supports": ["trend", "post", "draft"],
        "binding_steps": [
            "Prepare a Reddit developer app and OAuth environment variables: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN.",
            "Use Reddit as a trend source first; collect subreddit topics with rate limits and a clear User-Agent.",
            "Promotion output is staged as a local human-review draft by default, not auto-posted.",
            "Before posting, verify subreddit rules, affiliation disclosure, duplicate risk, and content fit.",
        ],
    },
}


def platform_definition(platform):
    return PLATFORM_CATALOG.get(
        platform,
        {
            "key": platform,
            "label": platform,
            "group": "custom",
            "auth_modes": ["manual"],
            "supports": ["draft"],
            "binding_steps": [
                "确认该平台当前项目可用的 publisher 或手动交付方式。",
                "填写账号信息并保存。",
                "如有可用检测方式，可执行账号检测。",
            ],
        },
    )


def all_platforms():
    return [PLATFORM_CATALOG[key] for key in sorted(PLATFORM_CATALOG)]
