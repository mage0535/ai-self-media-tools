import os
from pathlib import Path


def _home():
    try:
        return Path.home()
    except RuntimeError:
        return Path.cwd()


def project_home():
    explicit = os.environ.get("CONTENT_PLATFORM_HOME")
    return Path(explicit) if explicit else _home() / ".ai-self-media-tools"


def agent_home():
    """Return the optional host-agent home without exposing a host-specific path."""
    explicit = os.environ.get("AGENT_HOME") or os.environ.get("HERMES_HOME")
    return Path(explicit) if explicit else _home() / ".agent"


def agent_scripts_dir():
    """Resolve optional host integrations through an explicit, portable adapter."""
    explicit = os.environ.get("CONTENT_PLATFORM_AGENT_SCRIPTS_DIR")
    return Path(explicit) if explicit else agent_home() / "scripts"


def style_guide_path():
    explicit = os.environ.get("CONTENT_PLATFORM_STYLE_GUIDE")
    return Path(explicit) if explicit else project_home() / "skills" / "content" / "content-copywriting-style" / "SKILL.md"


def trend_cache_dir():
    explicit = os.environ.get("CONTENT_PLATFORM_TREND_CACHE_DIR")
    return Path(explicit) if explicit else project_home() / "data" / "trend-cache"


def social_auto_upload_home():
    explicit = os.environ.get("SOCIAL_AUTO_UPLOAD_HOME")
    if explicit:
        return Path(explicit)
    bundled = project_home() / "external" / "social-auto-upload"
    if bundled.exists():
        return bundled
    sibling = _home() / "social-auto-upload"
    if sibling.exists():
        return sibling
    return bundled


def browser_profile_roots():
    home = _home()
    return {
        "chromium": home / ".config" / "chromium",
        "google_chrome": home / ".config" / "google-chrome",
        "chrome_for_testing": home / ".config" / "google-chrome-for-testing",
    }
