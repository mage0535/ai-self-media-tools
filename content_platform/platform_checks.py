import os
from pathlib import Path

from .paths import social_auto_upload_home


PLATFORM_REQUIREMENTS = {
    "wechat": {"envs": ["WECHAT_APP_ID", "WECHAT_APP_SECRET"], "tools": ["image_script"]},
    "xiaohongshu": {"social_auto_upload": True, "tools": ["image_script"]},
    "douyin": {"social_auto_upload": True, "tools": ["video_script"]},
    "bilibili": {"social_auto_upload": True, "tools": ["video_script"]},
    "youtube": {"envs": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"], "tools": ["video_script"]},
    "linkedin": {"envs": ["LINKEDIN_ACCESS_TOKEN"], "tools": []},
    "devto": {"envs": ["DEVTO_API_KEY"], "tools": []},
    "telegraph": {"envs": ["TELEGRAPH_TOKEN"], "tools": []},
    "mastodon": {"envs": ["MASTODON_TOKEN"], "tools": []},
    "bluesky": {"envs": ["BLUESKY_IDENTIFIER", "BLUESKY_PASSWORD"], "tools": []},
}


def _account_name(binding):
    config = binding.get("config") or {}
    return config.get("account_name") or binding.get("account_key") or "default"


def _social_account_candidates(platform, account_name, project_dir=""):
    root = (Path(project_dir) if project_dir else social_auto_upload_home()) / "cookies"
    legacy_dirs = {
        "douyin": root / "douyin_uploader" / f"{account_name}.json",
        "kuaishou": root / "ks_uploader" / f"{account_name}.json",
        "xiaohongshu": root / "xiaohongshu_uploader" / f"{account_name}.json",
        "tiktok": root / "tk_uploader" / f"{account_name}.json",
    }
    candidates = [root / f"{platform}_{account_name}.json"]
    if platform in legacy_dirs:
        candidates.append(legacy_dirs[platform])
    return candidates


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
    if requirements.get("social_auto_upload"):
        account_name = _account_name(binding)
        publisher_cfg = readiness.get("publishers", {}).get(platform, {})
        binding_cfg = binding.get("config") or {}
        project_dir = binding_cfg.get("project_dir") or binding.get("project_dir") or ""
        candidates = _social_account_candidates(platform, account_name, project_dir)
        if not any(path.exists() for path in candidates):
            missing.append(" or ".join(str(path) for path in candidates))
        social_tool = publisher_cfg if publisher_cfg.get("type") == "social-auto-upload" else readiness.get("tools", {}).get("social_auto_upload", {})
        if not social_tool.get("project_dir_exists") or not social_tool.get("python_bin_exists"):
            missing.append("social-auto-upload runtime")
        cli_probe = social_tool.get("cli_probe") or {}
        if cli_probe and not cli_probe.get("available"):
            missing.append("social-auto-upload CLI: " + cli_probe.get("error", "unavailable"))
    content_tools = readiness.get("tools", {}).get("content_tools", {})
    for tool in requirements.get("tools", []):
        if not content_tools.get(tool, {}).get("available", False):
            missing.append(tool)
    if binding.get("credentials_ref"):
        notes.append(f"credentials_ref={binding['credentials_ref']}")
    if missing:
        return {"status": "pending", "error": "missing: " + ", ".join(missing), "notes": notes}
    return {"status": "connected", "error": "", "notes": notes}
