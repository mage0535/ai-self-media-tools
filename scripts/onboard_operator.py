#!/usr/bin/env python3
"""Beginner-friendly onboarding wizard for a new operator.

The script prints step-by-step guidance and performs safe local checks. It never
prints cookie contents, API keys, proxy nodes, or browser storage-state values.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = ROOT / "config.example.json"
CONFIG_LOCAL = ROOT / "config.json"


PLATFORMS = {
    "wechat": {
        "name": "WeChat Official Account / 公众号",
        "mode": "Draft API or Hermes adapter",
        "steps": [
            "Prepare your own WeChat Official Account AppID and AppSecret.",
            "Store secrets in your own .env or secrets/provider.env file; do not paste them into README or Git.",
            "Enable the wechat/wechat-draft publisher in config.json.",
            "Run: python -m content_platform health-refresh --platform wechat",
            "Create one draft first. Verify it in the platform draft box before any public publish.",
        ],
    },
    "kuaishou": {
        "name": "Kuaishou / 快手",
        "mode": "Automated upload with postcheck",
        "steps": [
            "Install and log in to your own social-auto-upload runtime.",
            "Keep Kuaishou cookies in the external runtime cookies folder, not in this repository.",
            "Set SOCIAL_AUTO_UPLOAD_HOME or configure the social-auto-upload path in config.json.",
            "Run: python -m content_platform delivery-readiness",
            "Run: python -m content_platform health-refresh --platform kuaishou",
            "Only upload packets that pass validate_kuaishou_auto_packet.py and postcheck.",
        ],
    },
    "douyin": {
        "name": "Douyin / 抖音",
        "mode": "Manual review package by default",
        "steps": [
            "Create a complete local package: video, title, body, cover, topics, and schedule suggestion.",
            "Use your own logged-in browser or mobile app to publish manually unless you have a verified uploader.",
            "Do not reuse another operator's Douyin cookie or browser profile.",
            "Run the quality gate before handoff. Do not publish off-lane content.",
        ],
    },
    "shipinhao": {
        "name": "Video Channels / 视频号",
        "mode": "Manual review package by default",
        "steps": [
            "Generate video, title, body, cover, topics, ending card, and QR/CTA evidence.",
            "Use your own WeChat/Video Channels login state.",
            "Run health-refresh and verify handoff package readiness.",
            "Publish manually unless a current verified uploader and postcheck route is configured.",
        ],
    },
    "bilibili": {
        "name": "Bilibili / B站",
        "mode": "Draft/file package or configured uploader",
        "steps": [
            "Prepare tutorial-style video or article content.",
            "If using social-auto-upload, log in with your own Bilibili account in that runtime.",
            "Run: python -m content_platform health-refresh --platform bilibili",
            "Check title, category, cover, tags, captions, and video clarity before upload.",
        ],
    },
    "xiaohongshu": {
        "name": "Xiaohongshu / 小红书",
        "mode": "Manual review package by default",
        "steps": [
            "Generate image-text notes, knowledge blocks, or short-video packages.",
            "Use real-scene images/materials matched to the copy.",
            "Publish manually from your own Xiaohongshu account unless you have a verified uploader.",
            "Check AI-feel, save value, cover, title, topics, and compliance before posting.",
        ],
    },
    "toutiao": {
        "name": "Toutiao / 今日头条",
        "mode": "Draft/article package",
        "steps": [
            "Generate a developed article with hook, sections, images, title, and tags.",
            "Store your own cookie/browser state outside this repository if using browser automation.",
            "Run health-refresh for the platform after configuring the publisher route.",
            "Start with draft or manual review, not direct public publish.",
        ],
    },
    "juejin": {
        "name": "Juejin / 掘金",
        "mode": "Draft/article package",
        "steps": [
            "Generate a technical article or open-source project analysis.",
            "Use your own Juejin cookie or token outside this repository.",
            "Run the article quality gate before draft creation.",
            "Verify the draft detail or draft list after submission.",
        ],
    },
    "zhihu": {
        "name": "Zhihu / 知乎",
        "mode": "Draft/article package",
        "steps": [
            "Generate a reasoned long-form answer or article with a clear point of view.",
            "Use your own Zhihu cookie/browser profile outside this repository.",
            "Run article quality checks before draft creation.",
            "Verify draft state; public 404 for a draft is not proof of failure.",
        ],
    },
    "youtube": {
        "name": "YouTube / YouTube Shorts",
        "mode": "Manual package or verified uploader",
        "steps": [
            "Prepare your own Google/YouTube channel login and keep browser state outside this repository.",
            "Generate video, title, description, tags, thumbnail, captions, and publish-time suggestion.",
            "Use an international network route that can access YouTube.",
            "Start with manual upload. Enable automation only after upload, visibility, and postcheck are verified.",
        ],
    },
    "tiktok": {
        "name": "TikTok",
        "mode": "Source discovery, localization, or manual package",
        "steps": [
            "Use an international network route that can access TikTok.",
            "For repost/localization workflows, keep source URL, video ID, caption, visual evidence, and license/compliance notes.",
            "Do not treat a downloaded clip as ready content. It must be localized, edited, deduped, captioned, and quality-checked.",
            "Manual publishing is recommended unless a current verified uploader exists.",
        ],
    },
    "reddit": {
        "name": "Reddit",
        "mode": "Trend collector and draft package",
        "steps": [
            "Create your own Reddit app if enabling OAuth trend collection.",
            "Store REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_REFRESH_TOKEN in a private env file.",
            "Use Reddit mainly for trend discovery and human-reviewed community drafts.",
            "Check subreddit rules before posting. The default publisher does not auto-post.",
        ],
    },
    "devto": {
        "name": "Dev.to",
        "mode": "Draft/API package",
        "steps": [
            "Create your own Dev.to API key and store it in DEVTO_API_KEY outside Git.",
            "Generate English technical articles with clear examples and source links.",
            "Start with drafts. Verify tags, canonical URL, and readability before publishing.",
        ],
    },
    "telegraph": {
        "name": "Telegraph",
        "mode": "API or file publish",
        "steps": [
            "Use Telegraph for lightweight linkable articles.",
            "Avoid putting private account data or secret links into public pages.",
            "Verify generated HTML/Markdown before publishing.",
        ],
    },
    "mastodon": {
        "name": "Mastodon",
        "mode": "API publisher",
        "steps": [
            "Choose your Mastodon instance and create an access token.",
            "Store instance URL and token in private environment variables.",
            "Keep posts concise, disclose affiliation where needed, and avoid duplicate blasts.",
        ],
    },
    "bluesky": {
        "name": "Bluesky",
        "mode": "API publisher",
        "steps": [
            "Prepare your Bluesky handle and app password.",
            "Store credentials outside Git.",
            "Use link-card previews and concise hooks. Verify identity before enabling automated posts.",
        ],
    },
    "nostr": {
        "name": "Nostr",
        "mode": "Signed publisher",
        "steps": [
            "Create or import your own Nostr private key in a private runtime only.",
            "Configure trusted relays.",
            "Never paste the private key into README, issue comments, chat logs, or tracked config.",
        ],
    },
    "writeas": {
        "name": "Write.as",
        "mode": "API publisher",
        "steps": [
            "Create your own API key and store it in WRITEAS_API_KEY.",
            "Use it for lightweight blog-style articles.",
            "Verify public/private visibility before publishing.",
        ],
    },
    "buttondown": {
        "name": "Buttondown",
        "mode": "Newsletter API publisher",
        "steps": [
            "Create your own Buttondown API key and keep it outside Git.",
            "Generate newsletter-ready subject, preview text, body, and links.",
            "Send tests to yourself before enabling a real campaign.",
        ],
    },
    "linkedin": {
        "name": "LinkedIn",
        "mode": "Manual package by default",
        "steps": [
            "Generate professional posts, article drafts, or link distribution copy.",
            "Manual publishing is recommended unless you have a verified API route.",
            "Check compliance with LinkedIn account and automation policies before adding automation.",
        ],
    },
    "x": {
        "name": "X / Twitter",
        "mode": "Manual package by default",
        "steps": [
            "Generate short posts, threads, or link distribution copy.",
            "Manual publishing is recommended by default because account risk can be high.",
            "If using API access, store keys in private environment variables and verify rate limits.",
        ],
    },
}


def run_check(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip().splitlines()
    detail = output[-1] if output else f"exit={result.returncode}"
    return result.returncode == 0, detail[:180]


def print_step(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def check_environment() -> bool:
    print_step("Step 1 - Local environment checks")
    checks = [
        ("Python", [sys.executable, "--version"]),
        ("Project audit", [sys.executable, "-m", "content_platform", "project-audit"]),
        ("Channel rulebook", [sys.executable, "scripts/validate_channel_rulebook.py"]),
        ("Git", ["git", "--version"]),
        ("ffmpeg", ["ffmpeg", "-version"]),
    ]
    all_ok = True
    for label, command in checks:
        ok, detail = run_check(command)
        all_ok = all_ok and (ok or label == "ffmpeg")
        mark = "OK" if ok else ("OPTIONAL" if label == "ffmpeg" else "NEEDS FIX")
        print(f"[{mark}] {label}: {detail}")
    if not shutil.which("ffmpeg"):
        print("ffmpeg is optional for article-only use, but required for video rendering.")
    return all_ok


def write_config() -> None:
    print_step("Step 2 - Local configuration")
    if CONFIG_LOCAL.exists():
        print("config.json already exists. It was not overwritten.")
        return
    if not CONFIG_EXAMPLE.exists():
        raise SystemExit("config.example.json is missing.")
    payload = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    CONFIG_LOCAL.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Created config.json from config.example.json.")
    print("Next: open config.json and replace placeholders with your own paths/accounts.")


def show_platform(platform: str) -> None:
    item = PLATFORMS[platform]
    print_step(f"Platform setup - {item['name']}")
    print(f"Default mode: {item['mode']}")
    for index, step in enumerate(item["steps"], 1):
        print(f"{index}. {step}")


def show_all_platforms() -> None:
    print_step("Step 3 - Platform binding guide")
    print("Choose one platform at a time. Do not try to bind every platform on day one.")
    domestic = ["wechat", "kuaishou", "douyin", "shipinhao", "bilibili", "xiaohongshu", "toutiao", "juejin", "zhihu"]
    international = ["youtube", "tiktok", "reddit", "devto", "telegraph", "mastodon", "bluesky", "nostr", "writeas", "buttondown", "linkedin", "x"]
    print("\nDomestic platforms:")
    for key in domestic:
        print(f"- {key}: {PLATFORMS[key]['name']} ({PLATFORMS[key]['mode']})")
    print("\nInternational platforms:")
    for key in international:
        print(f"- {key}: {PLATFORMS[key]['name']} ({PLATFORMS[key]['mode']})")
    print("\nExample: python scripts/onboard_operator.py --platform kuaishou")


def show_workflow() -> None:
    print_step("Step 4 - Safe workflow")
    print("1. Run operations analysis and choose a platform-specific topic.")
    print("2. Generate a draft or review package.")
    print("3. Run quality gates and privacy audit.")
    print("4. For semi-automatic platforms, publish manually from your own account.")
    print("5. For automated platforms, require health-refresh, delivery-readiness, and postcheck.")
    print("6. Record performance metrics after publishing.")
    print("\nRecommended commands:")
    print("  python -m content_platform delivery-readiness")
    print("  python -m content_platform health-refresh")
    print("  python -m content_platform feedback-summary")
    print("  python scripts/release_bundle.py --target ./public-bundle")


def main() -> int:
    parser = argparse.ArgumentParser(description="Beginner onboarding wizard for AI Self-Media Tools")
    parser.add_argument("--check", action="store_true", help="Only run safe local checks")
    parser.add_argument("--write-config", action="store_true", help="Create config.json from config.example.json if missing")
    parser.add_argument("--platform", choices=sorted(PLATFORMS), help="Show setup guide for one platform")
    args = parser.parse_args()

    ok = check_environment()
    if args.write_config:
        write_config()
    elif not args.check and not CONFIG_LOCAL.exists():
        print("\nconfig.json is missing. Run with --write-config to create it from the example.")

    if args.platform:
        show_platform(args.platform)
    elif not args.check:
        show_all_platforms()
        show_workflow()

    print_step("Privacy reminder")
    print("Never share config.json, .env files, data/, secrets/, cookies/, logs/, artifacts/, or browser profiles.")
    print("Use scripts/release_bundle.py when sharing this project with another person.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
