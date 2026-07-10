import os
from pathlib import Path


def project_home():
    return Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))


def style_guide_path():
    return Path(os.environ.get("CONTENT_PLATFORM_STYLE_GUIDE", project_home() / "skills" / "content" / "content-copywriting-style" / "SKILL.md"))


def trend_cache_dir():
    return Path(os.environ.get("CONTENT_PLATFORM_TREND_CACHE_DIR", project_home() / "data" / "trend-cache"))


def social_auto_upload_home():
    explicit = os.environ.get("SOCIAL_AUTO_UPLOAD_HOME")
    if explicit:
        return Path(explicit)
    bundled = project_home() / "external" / "social-auto-upload"
    if bundled.exists():
        return bundled
    sibling = Path.home() / "social-auto-upload"
    if sibling.exists():
        return sibling
    return bundled


def browser_profile_roots():
    home = Path.home()
    return {
        "chromium": home / ".config" / "chromium",
        "google_chrome": home / ".config" / "google-chrome",
        "chrome_for_testing": home / ".config" / "google-chrome-for-testing",
    }
