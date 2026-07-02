from pathlib import Path
from .paths import browser_profile_roots, social_auto_upload_home
from .tool_registry import ToolRegistry


def _cookie_count(path):
    base = Path(path)
    if not base.exists():
        return 0
    return sum(1 for _ in base.glob("*"))


def inspect_delivery_readiness(config):
    publishers = config.get("publishers", {}).get("platforms", {})
    result = {"publishers": {}, "tools": {}}
    for name, cfg in sorted(publishers.items()):
        kind = cfg.get("type", "file")
        item = {"type": kind}
        if kind in {"aitoearn-draft", "aitoearn-flow"}:
            env_file = cfg.get("env_file", "")
            item["env_file_exists"] = Path(env_file).is_file() if env_file else False
            item["base_url"] = cfg.get("base_url", "")
        elif kind == "social-auto-upload":
            project_dir = cfg.get("project_dir", str(social_auto_upload_home()))
            python_bin = cfg.get("python_bin", f"{project_dir}/venv/bin/python")
            item["project_dir_exists"] = Path(project_dir).is_dir()
            item["python_bin_exists"] = Path(python_bin).is_file()
            item["account_name"] = cfg.get("account_name", "")
        elif kind == "wechat-draft":
            env_file = cfg.get("env_file", "")
            item["env_file_exists"] = Path(env_file).is_file() if env_file else False
        result["publishers"][name] = item

    social_root = social_auto_upload_home()
    result["tools"]["social_auto_upload"] = {
        "project_dir_exists": social_root.is_dir(),
        "python_bin_exists": (social_root / "venv/bin/python").is_file(),
        "cookie_counts": {
            "douyin": _cookie_count(social_root / "cookies/douyin_uploader"),
            "kuaishou": _cookie_count(social_root / "cookies/ks_uploader"),
            "xiaohongshu": _cookie_count(social_root / "cookies/xiaohongshu_uploader"),
            "tiktok": _cookie_count(social_root / "cookies/tk_uploader"),
            "tencent": _cookie_count(social_root / "cookies/tencent_uploader"),
        },
    }
    result["tools"]["browser_profiles"] = {
        "chromium_exists": browser_profile_roots()["chromium"].exists(),
        "google_chrome_exists": browser_profile_roots()["google_chrome"].exists(),
        "chrome_for_testing_exists": browser_profile_roots()["chrome_for_testing"].exists(),
    }
    result["tools"]["content_tools"] = ToolRegistry(config).probe()
    return result
