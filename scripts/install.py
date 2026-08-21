#!/usr/bin/env python3
"""Beginner-friendly installer for AI Self-Media Tools.

The installer creates a private runtime skeleton and performs local checks. It
does not ask for, print, or persist real cookies/API keys/proxy nodes.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


AGENTS = ["hermes", "codex", "claude", "opencode", "qwen"]
OPTIONAL_TOOLS = ["git", "ffmpeg", "yt-dlp"]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def install_root() -> Path:
    return Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))


def social_root(home: Path) -> Path:
    return Path(os.environ.get("SOCIAL_AUTO_UPLOAD_HOME", home / "external" / "social-auto-upload"))


def style_path(home: Path) -> Path:
    override = os.environ.get("CONTENT_PLATFORM_STYLE_GUIDE")
    if override:
        return Path(override)
    local_skill = project_root() / "skills" / "content" / "content-copywriting-style" / "SKILL.md"
    if local_skill.exists():
        return local_skill
    return home / "skills" / "content" / "content-copywriting-style" / "SKILL.md"


def run(command: list[str], *, timeout: int = 180) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=project_root(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout_tail": "\n".join((result.stdout or "").splitlines()[-8:]),
            "stderr_tail": "\n".join((result.stderr or "").splitlines()[-8:]),
        }
    except Exception as exc:  # pragma: no cover - platform-specific diagnostics
        return {"ok": False, "returncode": None, "error": str(exc)}


def detect_agents() -> list[str]:
    return [name for name in AGENTS if shutil.which(name)]


def detect_tools() -> dict[str, bool]:
    return {name: bool(shutil.which(name)) for name in OPTIONAL_TOOLS}


def ensure_runtime_dirs(home: Path) -> None:
    for rel in [
        "data",
        "data/outbox",
        "data/drafts",
        "data/reports",
        "secrets",
        "cookies",
        "logs",
        "artifacts",
        "external/scripts",
    ]:
        (home / rel).mkdir(parents=True, exist_ok=True)


def render_config(home: Path, *, overwrite: bool = False) -> Path:
    template = {
        "data_dir": str(home / "data"),
        "generator": {
            "provider": "hermes-cli",
            "allow_fallback": False,
            "env_file": str(home / "secrets" / "provider.env"),
            "api_key_env": "OPENAI_API_KEY",
            "model": "",
            "hermes_command": "hermes",
            "hermes_provider": "",
            "hermes_model": "",
            "timeout": 180,
            "style_guide_path": str(style_path(home)),
        },
        "feature_flags": {
            "real_platform_trend_evidence_mode": "enforce",
            "topic_scoring_mode": "enforce",
            "quality_gate_enhanced": "enforce",
            "duplication_detector": "enforce",
            "run_contract": "enforce",
            "asset_ledger": "enforce",
            "viral_cover_gate": "enforce",
        },
        "workflow": {"require_gate_pass": True, "require_unified_acceptance": True},
            "resources": {"min_available_mb": 1200, "warning_disk_used_percent": 84, "max_disk_used_percent": 88, "video_max_disk_used_percent": 87},
        "media": {
            "image": {
                "enabled": True,
                "script": str(home / "external" / "scripts" / "image_gen.py"),
                "method": "auto",
                "provider": "auto",
                "model": "",
                "size": "1024x1024",
                "quality": "low",
                "timeout": 240,
            },
            "video": {
                "enabled": True,
                "platforms": ["douyin", "bilibili", "youtube", "tiktok", "kuaishou", "shipinhao"],
                "script": str(home / "external" / "scripts" / "video_pipeline.py"),
                "visual_image_count": 8,
                "timeout": 600,
            },
            "audio": {
                "enabled": True,
                "platforms": ["douyin", "bilibili", "youtube", "tiktok", "kuaishou", "shipinhao"],
                "mode": "auto",
                "timeout": 300,
            },
        },
        "content_policy": {
            "original_content": "image_text_only",
            "short_video": "original_or_repurpose_by_ops_analysis",
            "allow_local_video_generation": True,
            "allow_local_audio_generation": True,
        },
        "content_hygiene": {
            "enabled": True,
            "candidate_limit": 200,
            "block_threshold": 0.72,
            "review_threshold": 0.58,
        },
        "ocr": {"script": str(home / "external" / "scripts" / "ocr_pipeline.py"), "timeout": 120},
        "transcription": {"script": str(home / "external" / "scripts" / "transcribe_pipeline.py"), "timeout": 300},
        "analysis": {"script": str(home / "external" / "scripts" / "multimodal_analyze.py"), "timeout": 180},
        "trends": {
            "legacy_data_dir": str(home / "data" / "trend-cache"),
            "legacy_script": str(home / "external" / "scripts" / "trend_collector.py"),
            "legacy_timeout": 20,
            "max_total_seconds": 45,
            "fallback_enabled": True,
            "reddit": {
                "enabled": False,
                "client_id_env": "REDDIT_CLIENT_ID",
                "client_secret_env": "REDDIT_CLIENT_SECRET",
                "refresh_token_env": "REDDIT_REFRESH_TOKEN",
                "user_agent": "ai-self-media-tools/1.0.0 by configured-operator",
                "subreddits": ["SideProject", "ArtificialInteligence", "Entrepreneur"],
                "keywords": ["AI workflow", "automation", "content operations"],
                "limit_per_subreddit": 25,
                "sort": "hot",
                "time_filter": "week",
            },
        },
        "publishers": {
            "routing_defaults": {
                "enabled": True,
                "domestic": {"type": "social-auto-upload", "account_name": "<account-alias>"},
                "international": {
                    "type": "manual-handoff",
                    "reason": "international auto publishing requires explicit per-platform cookie/API publisher",
                },
            },
            "platforms": {
                "reddit": {
                    "type": "reddit-draft",
                    "outbox": str(home / "data" / "outbox"),
                    "default_subreddit": "manual-selection",
                },
                "youtube": {"type": "file", "outbox": str(home / "data" / "outbox")},
                "tiktok": {"type": "file", "outbox": str(home / "data" / "outbox")},
                "devto": {"type": "devto-draft", "api_key_env": "DEVTO_API_KEY"},
                "telegraph": {"type": "telegraph"},
                "mastodon": {"type": "mastodon", "access_token_env": "MASTODON_ACCESS_TOKEN"},
                "bluesky": {"type": "bluesky", "password_env": "BLUESKY_APP_PASSWORD"},
                "nostr": {"type": "nostr", "private_key_env": "NOSTR_PRIVATE_KEY"},
                "writeas": {"type": "writeas", "api_key_env": "WRITEAS_API_KEY"},
                "buttondown": {"type": "buttondown", "api_key_env": "BUTTONDOWN_API_KEY"},
            },
            "default": {"type": "file", "outbox": str(home / "data" / "outbox")},
        },
        "notifications": {
            "log_path": str(home / "data" / "notifications.jsonl"),
            "network_enabled": True,
            "hermes_target_env": "AI_SELF_MEDIA_HERMES_TARGET",
        },
    }
    out = home / "config.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        return out
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def environment_report(home: Path) -> dict[str, Any]:
    checks = {
        "python_version": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 11),
        "platform": platform.platform(),
        "project_root": str(project_root()),
        "install_root": str(home),
        "agents": detect_agents(),
        "tools": detect_tools(),
        "social_auto_upload_home": str(social_root(home)),
    }
    checks["project_audit"] = run([sys.executable, "-m", "content_platform", "project-audit"], timeout=120)
    checks["channel_rulebook"] = run([sys.executable, "scripts/validate_channel_rulebook.py"], timeout=120)
    return checks


def install_dependencies() -> dict[str, Any]:
    return {
        "requirements": run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], timeout=600),
        "editable_install": run([sys.executable, "-m", "pip", "install", "-e", "."], timeout=600),
    }


def print_beginner_summary(mode: str, home: Path) -> None:
    print("AI Self-Media Tools installer")
    print(f"Mode: {mode}")
    print(f"Private runtime directory: {home}")
    print("")
    print("This installer does not collect cookies, API keys, proxy nodes, or account data.")
    print("After it finishes, run: python scripts/onboard_operator.py")
    print("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or check AI Self-Media Tools")
    parser.add_argument(
        "--mode",
        choices=["full", "check", "config-only"],
        default="full",
        help="full installs dependencies and writes runtime config; check is read-only; config-only writes runtime skeleton only",
    )
    parser.add_argument("--force-config", action="store_true", help="Overwrite runtime config.json template")
    args = parser.parse_args(argv)

    home = install_root()
    print_beginner_summary(args.mode, home)

    dependency_result: dict[str, Any] | None = None
    if args.mode != "check":
        ensure_runtime_dirs(home)
        config_path = render_config(home, overwrite=args.force_config)
    else:
        config_path = home / "config.json"

    if args.mode == "full":
        dependency_result = install_dependencies()

    report = environment_report(home)
    report["mode"] = args.mode
    report["config_path"] = str(config_path)
    report["dependency_install"] = dependency_result
    report["next_steps"] = [
        "Run: python scripts/onboard_operator.py",
        "Bind one platform at a time.",
        "Run project-audit and channel rulebook validation before real publishing.",
        "Keep cookies, API keys, proxies, generated works, and account data outside Git.",
    ]

    if args.mode != "check":
        report_path = home / "installation-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote installation report: {report_path}")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["python_ok"]:
        return 1
    if args.mode == "full" and dependency_result:
        if not dependency_result["requirements"]["ok"] or not dependency_result["editable_install"]["ok"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
