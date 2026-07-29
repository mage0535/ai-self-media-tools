#!/usr/bin/env python3
"""Preflight checks for the WeChat Official Account publishing workflow.

This script checks runtime readiness only. It never prints secret values.
"""

import glob
import json
import os
import sys
from pathlib import Path


FAILED = []


def check(desc: str, condition: bool, fix: str = "") -> None:
    if condition:
        print(f"  OK  {desc}")
    else:
        print(f"  FAIL {desc}")
        FAILED.append(f"{desc} - {fix}" if fix else desc)


def main() -> int:
    print("=" * 50)
    print("WeChat publishing preflight checklist")
    print("=" * 50)

    content_home = Path(
        os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools"))
    )
    env_file = content_home / "secrets" / "wechat.env"

    check("CN_PROXY is configured", bool(os.environ.get("CN_PROXY")), "set CN_PROXY")
    check("wechat.env exists", env_file.exists(), "create secrets/wechat.env")

    if env_file.exists():
        env_data = env_file.read_text(encoding="utf-8", errors="ignore")
        app_id_key = "WECHAT_APP_ID="
        app_secret_key = "WECHAT_APP_" + "SECRET="
        check("WECHAT_APP_ID is present", app_id_key in env_data)
        check("WECHAT_APP_SECRET is present", app_secret_key in env_data)

    themes_dir = Path(
        os.environ.get(
            "HERMES_WECHAT_THEMES_DIR",
            str(Path.home() / ".hermes" / "tools" / "wechat-themes"),
        )
    )
    theme_files = sorted(glob.glob(str(themes_dir / "*.json")))
    check(
        f"WeChat theme library is complete ({len(theme_files)}/109)",
        len(theme_files) >= 109,
        "install the WeChat theme pack",
    )

    if theme_files:
        try:
            sample = json.loads(Path(theme_files[0]).read_text(encoding="utf-8"))
            has_styles = "styles" in sample and "h2" in sample.get("styles", {})
        except Exception:
            has_styles = False
        check(
            "Theme JSON has styles.h2",
            has_styles,
            "theme JSON must include styles.h2 and related style keys",
        )

    scripts_dir = Path(
        os.environ.get("HERMES_SCRIPTS_DIR", str(Path.home() / ".hermes" / "scripts"))
    )
    check(
        "image_gen_engine.py exists",
        (scripts_dir / "image_gen_engine.py").exists(),
        "install the WeChat image engine",
    )

    print("\nRequired content rules:")
    print("  - Use platform trend data before choosing the topic.")
    print("  - Write at least 1200 Chinese characters before publishing.")
    print("  - Use content-relevant cover and inline images.")
    print("  - Apply a suitable WeChat theme template, not the default layout.")
    print("  - Include at least one quote block and one list where appropriate.")
    print("  - Report every step and decision during the workflow.")

    print("\n" + "=" * 50)
    if FAILED:
        print(f"FAIL {len(FAILED)} checks did not pass:")
        for failure in FAILED:
            print(f"  - {failure}")
        return 1

    print("OK all checks passed; WeChat publishing workflow can start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
