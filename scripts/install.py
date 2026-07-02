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
        "publishers": {
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
