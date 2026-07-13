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
                "script": str(home / "external" / "scripts" / "image_gen.py"),
                "method": "pil",
                "timeout": 120,
            },
            "video": {
                "enabled": False,
                "platforms": ["douyin", "bilibili", "youtube", "tiktok", "kuaishou", "shipinhao"],
                "script": str(home / "external" / "scripts" / "video_pipeline.py"),
                "timeout": 600,
            },
            "audio": {
                "enabled": False,
                "platforms": ["douyin", "bilibili", "youtube", "tiktok", "kuaishou", "shipinhao"],
                "mode": "auto",
                "timeout": 300,
            },
        },
        "content_policy": {
            "original_content": "image_text_only",
            "short_video": "repurpose_existing_source_only",
            "allow_local_video_generation": False,
            "allow_local_audio_generation": False,
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
        "publishers": {
            "routing_defaults": {
                "enabled": True,
                "domestic": {"type": "social-auto-upload", "account_name": "<account-alias>"},
                "international": {
                    "type": "aitoearn-draft",
                    "base_url": "https://aitoearn.ai/api/unified/mcp",
                    "api_key_env": "AITOEARN_INTL_API_KEY",
                },
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
