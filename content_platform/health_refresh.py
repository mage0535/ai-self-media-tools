"""Refresh delivery health from current runtime probes.

The refresher is intentionally conservative: it only marks a channel usable
when the configured publisher can be probed without relying on historical
manual success. Otherwise it writes a blocking state with a concrete reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_policy import platform_region
from .content_policy import is_douyin_platform, is_manual_handoff_platform
from .auth_registry import cookie_file_status, resolve_cookie_file
from .publishers import read_setting


DOMESTIC_POSTCHECK_PLATFORMS = {"douyin", "kuaishou", "wechat", "shipinhao", "bilibili", "juejin", "zhihu"}

TOKEN_PUBLISHERS = {
    "devto-draft": ["api_key_env"],
    "telegraph": ["token_env"],
    "mataroa": ["api_key_env"],
    "mastodon": ["token_env"],
    "nostr": ["key_env"],
    "writeas": ["token_env"],
    "buttondown": ["api_key_env"],
}

MULTI_SECRET_PUBLISHERS = {
    "bluesky": ["identifier_env", "password_env"],
}

AITOEARN_DISABLED_PLATFORMS = {"youtube", "tiktok", "twitter", "x", "threads"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env_present(name: str, env_file: str = "") -> bool:
    return bool(read_setting(name, env_file))


def _proxy_state(platform: str) -> tuple[bool, str]:
    region = platform_region(platform)
    if region == "domestic" and not os.environ.get("CN_PROXY"):
        return False, "missing CN_PROXY"
    if region == "international" and not os.environ.get("US_PROXY"):
        return False, "missing US_PROXY"
    return True, ""


def _social_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    project_dir = Path(str(cfg.get("project_dir", ""))).expanduser()
    python_bin = Path(str(cfg.get("python_bin", ""))).expanduser()
    platform_name = str(cfg.get("platform_name") or "")
    account_name = str(cfg.get("account_name") or "")
    if not project_dir.is_dir():
        return False, "social-auto-upload project_dir missing"
    if not python_bin.is_file():
        return False, "social-auto-upload python_bin missing"
    if not platform_name or not account_name:
        return False, "social-auto-upload platform_name/account_name missing"
    try:
        proc = subprocess.run(
            [str(python_bin), "sau_cli.py", platform_name, "check", "--account", account_name],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except Exception as exc:
        return False, f"social-auto-upload check failed to start: {str(exc)[:160]}"
    text = f"{proc.stdout}\n{proc.stderr}".casefold()
    if proc.returncode == 0 and "valid" in text:
        return True, "social-auto-upload account check valid"
    return False, "social-auto-upload account check invalid"


def _wechat_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    command = Path(str(cfg.get("adapter_command", ""))).expanduser()
    env_file = str(cfg.get("env_file", ""))
    if not command.is_file():
        return False, "WeChat adapter command missing"
    if not _env_present("WECHAT_APP_ID", env_file) or not _env_present("WECHAT_APP_SECRET", env_file):
        return False, "WeChat credentials missing"
    if cfg.get("require_cn_proxy", True) and not os.environ.get("CN_PROXY"):
        return False, "missing CN_PROXY"
    return True, "WeChat adapter and credentials present"


def _aitoearn_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    env_file = str(cfg.get("env_file", ""))
    key_env = str(cfg.get("api_key_env") or "AITOEARN_API_KEY")
    if not cfg.get("account_id"):
        return False, "AiToEarn account_id missing"
    if not _env_present(key_env, env_file):
        return False, f"{key_env} missing"
    return True, "AiToEarn account and key present"


def _cookie_file(cfg: dict[str, Any], platform: str) -> Path:
    account = str(cfg.get("account") or "main")
    return resolve_cookie_file(platform, account, str(cfg.get("cookie_dir", "")))


def _cookie_json_check(cfg: dict[str, Any], platform: str) -> tuple[bool, str]:
    cookie_file = _cookie_file(cfg, platform)
    status = cookie_file_status(cookie_file, platform)
    if not status.get("exists"):
        return False, f"{platform} cookie not found"
    if not status.get("valid"):
        missing = ",".join(status.get("required_names_missing", []))
        detail = f" missing required names: {missing}" if missing else ""
        return False, f"{platform} cookie file invalid or empty{detail}"
    return True, f"{platform} cookie present at {cookie_file}"


def _zhihu_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _cookie_json_check(cfg, "zhihu")
    if not ok:
        return ok, reason
    if importlib.util.find_spec("playwright") is None:
        return False, "zhihu playwright dependency missing"
    return True, "zhihu cookie and playwright dependency present"


def _juejin_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _cookie_json_check(cfg, "juejin")
    if not ok:
        return ok, reason
    return True, "juejin cookie present"


def _x_check(cfg: dict[str, Any]) -> tuple[bool, str]:
    ok, reason = _cookie_json_check(cfg, "twitter")
    if not ok:
        return ok, reason
    if importlib.util.find_spec("playwright") is None:
        return False, "x playwright dependency missing"
    return True, "X/Twitter cookie and playwright dependency present"


def _env_publisher_check(kind: str, cfg: dict[str, Any]) -> tuple[bool, str]:
    env_file = str(cfg.get("env_file", ""))
    env_keys = TOKEN_PUBLISHERS.get(kind) or MULTI_SECRET_PUBLISHERS.get(kind) or []
    missing = []
    for cfg_key in env_keys:
        env_name = str(cfg.get(cfg_key) or "")
        if not env_name:
            missing.append(cfg_key)
            continue
        if not _env_present(env_name, env_file):
            missing.append(env_name)
    if kind == "mastodon" and not cfg.get("instance"):
        missing.append("instance")
    if missing:
        return False, "missing " + ", ".join(missing)
    return True, f"{kind} credentials present"


def classify_platform_health(platform: str, cfg: dict[str, Any]) -> dict[str, Any]:
    platform = str(platform)
    kind = str((cfg or {}).get("type", "file"))
    if is_manual_handoff_platform(platform):
        return _entry(
            "manual_handoff_only",
            False,
            f"{platform} is manual-only by operator policy; generate compliant local review packages only",
            "health_refresh",
        )
    proxy_ok, proxy_reason = _proxy_state(platform)
    if not proxy_ok:
        return _entry("proxy_unavailable", False, proxy_reason, "health_refresh")

    if kind == "social-auto-upload":
        ok, reason = _social_check(cfg)
        if ok:
            require_postcheck = platform in DOMESTIC_POSTCHECK_PLATFORMS or bool(cfg.get("postcheck_command"))
            state = "usable_with_postcheck_required" if require_postcheck else "usable"
            if is_douyin_platform(platform):
                reason = f"{reason}; daily single-work limit still applies"
            return _entry(state, True, reason, "health_refresh", require_postcheck=require_postcheck)
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "wechat-draft":
        ok, reason = _wechat_check(cfg)
        if ok:
            return _entry("usable_with_postcheck_required", True, reason, "health_refresh", require_postcheck=True)
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "aitoearn-flow":
        if platform.casefold() in AITOEARN_DISABLED_PLATFORMS:
            return _entry(
                "manual_handoff_only",
                False,
                f"{platform} is configured for cookie/manual route; AiToEarn is disabled by operator policy",
                "health_refresh",
            )
        ok, reason = _aitoearn_check(cfg)
        if ok:
            return _entry("usable", True, reason, "health_refresh")
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "juejin-api":
        ok, reason = _juejin_check(cfg)
        if ok:
            return _entry("usable_with_postcheck_required", True, reason, "health_refresh", require_postcheck=True)
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "zhihu-playwright":
        ok, reason = _zhihu_check(cfg)
        if ok:
            return _entry("usable_with_postcheck_required", True, reason, "health_refresh", require_postcheck=True)
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "x-playwright":
        ok, reason = _x_check(cfg)
        if ok:
            return _entry("usable", True, reason, "health_refresh")
        return _entry("auth_required", False, reason, "health_refresh")

    if kind in TOKEN_PUBLISHERS or kind in MULTI_SECRET_PUBLISHERS:
        ok, reason = _env_publisher_check(kind, cfg)
        if ok:
            return _entry("usable", True, reason, "health_refresh")
        return _entry("auth_required", False, reason, "health_refresh")

    if kind == "shipinhao-handoff":
        return _entry(
            "route_unverified",
            False,
            "Video Channels is configured as handoff only; upload/postcheck runner must verify before publish",
            "health_refresh",
        )

    if kind == "manual-handoff":
        return _entry("manual_handoff_only", False, f"{platform} is configured for local manual handoff only", "health_refresh")

    if kind in {"file", "playwright-article"}:
        return _entry("route_unverified", False, f"{kind} is a local handoff route, not a verified publisher", "health_refresh")

    return _entry("route_unverified", False, f"publisher type {kind} has no health refresher", "health_refresh")


def _entry(state: str, can_publish: bool, reason: str, source: str, require_postcheck: bool = False) -> dict[str, Any]:
    return {
        "state": state,
        "can_publish_now": can_publish,
        "require_postcheck": require_postcheck,
        "reason": reason,
        "source": source,
        "checked_at": _now(),
    }


def refresh_delivery_health(config: dict[str, Any], output_path: str | Path | None = None, platforms: list[str] | None = None) -> dict[str, Any]:
    publishers = (config.get("publishers") or {}).get("platforms") or {}
    selected = platforms or sorted(publishers)
    health = {
        "generated_at": _now(),
        "platforms": {},
    }
    for platform in selected:
        cfg = publishers.get(platform) or {}
        health["platforms"][platform] = classify_platform_health(platform, cfg)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
        health["path"] = str(path)
    return health
