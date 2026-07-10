from pathlib import Path
import subprocess
from .paths import browser_profile_roots, social_auto_upload_home
from .tool_registry import ToolRegistry


def _cookie_count(path, pattern="*"):
    base = Path(path)
    if not base.exists():
        return 0
    return sum(1 for _ in base.glob(pattern))


def _probe_social_cli(project_dir, python_bin):
    project = Path(project_dir)
    python = Path(python_bin)
    if not project.is_dir() or not python.is_file():
        return {"available": False, "error": "missing project_dir or python_bin"}
    try:
        result = subprocess.run(
            [str(python), "sau_cli.py", "--help"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)[:200]}
    if result.returncode == 0:
        return {"available": True, "error": ""}
    return {"available": False, "error": (result.stderr or result.stdout)[:200]}


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
        elif kind == "fallback":
            item["backends"] = [backend.get("type", "file") for backend in cfg.get("publishers", [])]
        elif kind == "social-auto-upload":
            project_dir = cfg.get("project_dir", str(social_auto_upload_home()))
            python_bin = cfg.get("python_bin", f"{project_dir}/venv/bin/python")
            item["project_dir_exists"] = Path(project_dir).is_dir()
            item["python_bin_exists"] = Path(python_bin).is_file()
            item["account_name"] = cfg.get("account_name", "")
            item["platform_name"] = cfg.get("platform_name", name)
            item["cli_probe"] = _probe_social_cli(project_dir, python_bin)
        elif kind == "wechat-draft":
            env_file = cfg.get("env_file", "")
            item["env_file_exists"] = Path(env_file).is_file() if env_file else False
        result["publishers"][name] = item

    social_root = social_auto_upload_home()
    python_bin = social_root / "venv/bin/python"
    result["tools"]["social_auto_upload"] = {
        "resolved_home": str(social_root),
        "project_dir_exists": social_root.is_dir(),
        "python_bin_exists": python_bin.is_file(),
        "cli_probe": _probe_social_cli(social_root, python_bin),
        "cookie_counts": {
            "douyin": _cookie_count(social_root / "cookies", "douyin_*.json") + _cookie_count(social_root / "cookies/douyin_uploader", "*.json"),
            "bilibili": _cookie_count(social_root / "cookies", "bilibili_*.json"),
            "kuaishou": _cookie_count(social_root / "cookies", "kuaishou_*.json") + _cookie_count(social_root / "cookies/ks_uploader", "*.json"),
            "xiaohongshu": _cookie_count(social_root / "cookies", "xiaohongshu_*.json") + _cookie_count(social_root / "cookies/xiaohongshu_uploader", "*.json"),
            "tiktok": _cookie_count(social_root / "cookies", "tiktok_*.json") + _cookie_count(social_root / "cookies/tk_uploader", "*.json"),
            "tencent": _cookie_count(social_root / "cookies/tencent_uploader", "*.json"),
        },
    }
    result["tools"]["browser_profiles"] = {
        "chromium_exists": browser_profile_roots()["chromium"].exists(),
        "google_chrome_exists": browser_profile_roots()["google_chrome"].exists(),
        "chrome_for_testing_exists": browser_profile_roots()["chrome_for_testing"].exists(),
    }
    probe_config = dict(config)
    probe_config.setdefault("fast_probe", True)
    result["tools"]["content_tools"] = ToolRegistry(probe_config).probe()
    return result
