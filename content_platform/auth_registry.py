"""Runtime cookie locator.

This module never returns cookie values. It only resolves ignored runtime files
so agents do not depend on remembering where an operator uploaded credentials.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SEARCH_DIRS = [
    "~/social-auto-upload/cookies",
    "~/.ai-self-media-tools/cookies",
    "~/.ai-self-media-tools/secrets/cookies",
    "~/.hermes/cookies",
    "~/.hermes/data",
    "~/.hermes/data/cookies",
]

REQUIRED_COOKIE_NAMES = {
    "juejin": {"sessionid", "csrf_token", "XSRF-TOKEN", "sso_jae_rem"},
    "zhihu": {"z_c0", "d_c0"},
    "bilibili": {"SESSDATA"},
    "douyin": {"sessionid", "sid_guard", "passport_csrf_token"},
    "xiaohongshu": {"web_session", "a1"},
    "kuaishou": {"kuaishou.server.web_st", "did", "userId"},
    "tiktok": {"sessionid", "sid_tt", "ttwid"},
    "youtube": {"SID", "HSID", "SSID", "SAPISID"},
    "twitter": {"auth_token", "ct0"},
    "x": {"auth_token", "ct0"},
}


def cookie_search_dirs(extra: list[str] | None = None) -> list[Path]:
    raw = []
    env_value = os.environ.get("CONTENT_PLATFORM_COOKIE_DIRS", "")
    if env_value:
        raw.extend(part for part in env_value.split(":") if part.strip())
    raw.extend(extra or [])
    raw.extend(DEFAULT_SEARCH_DIRS)
    result: list[Path] = []
    seen = set()
    for item in raw:
        path = _safe_path(item)
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def candidate_cookie_paths(platform: str, account: str = "main", cookie_dir: str = "") -> list[Path]:
    platform = normalize_platform(platform)
    account = str(account or "main")
    names = [
        f"{platform}_{account}.json",
        f"{platform}_{account}_cookies.json",
        f"{platform}_cookies.json",
        f"{platform}.json",
        f"{account}.json",
    ]
    aliases = {
        "x": ["twitter"],
        "twitter": ["x"],
        "tiktok": ["tk"],
        "shipinhao": ["tencent", "wxSph"],
        "wechat": ["wxGzh", "weixin"],
        "xiaohongshu": ["xhs", "rednote"],
    }
    for alias in aliases.get(platform, []):
        names.extend([f"{alias}_{account}.json", f"{alias}_cookies.json", f"{alias}.json"])

    roots = cookie_search_dirs([cookie_dir] if cookie_dir else [])
    paths: list[Path] = []
    seen = set()
    for root in roots:
        for name in names:
            for path in (root / name, root / f"{platform}_uploader" / name, root / f"{platform}_uploader" / account / name):
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
    return paths


def resolve_cookie_file(platform: str, account: str = "main", cookie_dir: str = "") -> Path:
    for path in candidate_cookie_paths(platform, account, cookie_dir):
        if path.is_file() and cookie_file_status(path, platform).get("valid"):
            return path
    for path in candidate_cookie_paths(platform, account, cookie_dir):
        if path.is_file():
            return path
    return candidate_cookie_paths(platform, account, cookie_dir)[0]


def cookie_file_status(path: Path, platform: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "valid": False,
        "format": "",
        "cookie_count": 0,
        "required_names_present": [],
        "required_names_missing": [],
    }
    if not path.is_file():
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"invalid json: {type(exc).__name__}"
        return result
    cookies = extract_cookies(payload)
    result["format"] = "playwright_storage_state" if isinstance(payload, dict) and "cookies" in payload else ("cookie_list" if isinstance(payload, list) else "unknown")
    result["cookie_count"] = len(cookies)
    names = {str(item.get("name") or "") for item in cookies if isinstance(item, dict)}
    required = REQUIRED_COOKIE_NAMES.get(normalize_platform(platform), set())
    present = sorted(name for name in required if name in names)
    missing = sorted(name for name in required if name not in names)
    result["required_names_present"] = present
    result["required_names_missing"] = missing
    result["valid"] = bool(cookies) and (not required or bool(present))
    return result


def extract_cookies(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        cookies = payload.get("cookies", [])
        return cookies if isinstance(cookies, list) else []
    if isinstance(payload, list):
        return payload
    return []


def cookie_inventory(platforms: list[str], account: str = "main", cookie_dir: str = "") -> dict[str, Any]:
    rows = {}
    for platform in platforms:
        candidates = candidate_cookie_paths(platform, account, cookie_dir)
        statuses = [cookie_file_status(path, platform) for path in candidates if path.is_file()]
        best = next((item for item in statuses if item.get("valid")), statuses[0] if statuses else cookie_file_status(candidates[0], platform))
        rows[platform] = {
            "resolved_path": best.get("path", ""),
            "exists": best.get("exists", False),
            "valid": best.get("valid", False),
            "format": best.get("format", ""),
            "cookie_count": best.get("cookie_count", 0),
            "required_names_present": best.get("required_names_present", []),
            "required_names_missing": best.get("required_names_missing", []),
            "candidate_count": len(candidates),
            "existing_candidates": [item.get("path", "") for item in statuses[:10]],
        }
    return {"platforms": rows}


def normalize_platform(platform: str) -> str:
    value = str(platform or "").casefold()
    if value == "rednote":
        return "xiaohongshu"
    if value == "wxgzh":
        return "wechat"
    return value


def _safe_path(value: str) -> Path:
    path = Path(str(value))
    try:
        return path.expanduser()
    except RuntimeError:
        return path
