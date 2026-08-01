import json
import os
import platform
import shutil
import sys
from pathlib import Path

AGENTS = ["hermes", "codex", "claude", "opencode", "qwen"]


def detect_agents():
    found = []
    for name in AGENTS:
        if shutil.which(name):
            found.append(name)
    return found


def project_root():
    return Path(__file__).resolve().parents[1]


def install_root():
    return Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))


def social_root(home: Path):
    return Path(os.environ.get("SOCIAL_AUTO_UPLOAD_HOME", home / "external" / "social-auto-upload"))


def style_path(home: Path):
    override = os.environ.get("CONTENT_PLATFORM_STYLE_GUIDE")
    if override:
        return Path(override)
    local_skill = project_root() / "skills" / "content" / "content-copywriting-style" / "SKILL.md"
    if local_skill.exists():
        return local_skill
    return home / "skills" / "content" / "content-copywriting-style" / "SKILL.md"


def render_config(home: Path):
    template = {
        "data_dir": str(home / "data"),
        "generator": {
            "provider": "hermes-cli",
            "allow_fallback": True,
            "env_file": str(home / "secrets" / "provider.env"),
            "api_key_env": "OPENAI_API_KEY",
            "model": "gpt-4.1-mini",
            "hermes_command": "hermes",
            "timeout": 180,
            "style_guide_path": str(style_path(home)),
        },
        "media": {
            "image": {
                "enabled": True,
                "script": str(home / "scripts" / "image_gen.py"),
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
                    "reason": "international auto publishing requires explicit per-platform cookie publisher",
                },
            },
            "platforms": {
                "reddit": {
                    "type": "reddit-draft",
                    "outbox": str(home / "data" / "outbox"),
                    "default_subreddit": "manual-selection",
                }
            },
            "default": {"type": "file", "outbox": str(home / "data" / "outbox")}
        },
        "notifications": {
            "log_path": str(home / "data" / "notifications.jsonl"),
            "network_enabled": False,
        },
    }
    out = home / "config.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    home = install_root()
    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    (home / "secrets").mkdir(exist_ok=True)
    (home / "external" / "scripts").mkdir(parents=True, exist_ok=True)
    report = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "agents": detect_agents(),
        "project_root": str(project_root()),
        "install_root": str(home),
        "social_auto_upload_home": str(social_root(home)),
        "config_path": str(render_config(home)),
    }
    report_path = home / "installation-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
