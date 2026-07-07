import os
from pathlib import Path

from .paths import social_auto_upload_home


PLATFORM_REQUIREMENTS = {
    "wechat": {"envs": ["WECHAT_APP_ID", "WECHAT_APP_SECRET"], "tools": ["image_script"]},
    "xiaohongshu": {"paths": [social_auto_upload_home() / "cookies" / "xiaohongshu_uploader"], "tools": ["image_script"]},
    "douyin": {"paths": [social_auto_upload_home() / "cookies" / "douyin_uploader"], "tools": ["video_script"]},
    "bilibili": {"envs": ["BILIBILI_SESSDATA"], "tools": ["video_script"]},
    "youtube": {"envs": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"], "tools": ["video_script"]},
    "linkedin": {"envs": ["LINKEDIN_ACCESS_TOKEN"], "tools": []},
    "devto": {"envs": ["DEVTO_API_KEY"], "tools": []},
    "telegraph": {"envs": ["TELEGRAPH_TOKEN"], "tools": []},
    "mastodon": {"envs": ["MASTODON_TOKEN"], "tools": []},
    "bluesky": {"envs": ["BLUESKY_IDENTIFIER", "BLUESKY_PASSWORD"], "tools": []},
}


def evaluate_platform_binding(platform, binding, readiness):
    platform = str(platform)
    binding = dict(binding or {})
    requirements = PLATFORM_REQUIREMENTS.get(platform, {"envs": [], "paths": [], "tools": []})
    missing = []
    notes = []
    for env_name in requirements.get("envs", []):
        if not os.environ.get(env_name):
            missing.append(env_name)
    for path in requirements.get("paths", []):
        if not Path(path).exists():
            missing.append(str(path))
    content_tools = readiness.get("tools", {}).get("content_tools", {})
    for tool in requirements.get("tools", []):
        if not content_tools.get(tool, {}).get("available", False):
            missing.append(tool)
    if binding.get("credentials_ref"):
        notes.append(f"credentials_ref={binding['credentials_ref']}")
    if missing:
        return {"status": "pending", "error": "missing: " + ", ".join(missing), "notes": notes}
    return {"status": "connected", "error": "", "notes": notes}
