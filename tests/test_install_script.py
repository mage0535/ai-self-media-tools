import json
import os
import subprocess
import sys
from pathlib import Path


def test_install_check_mode_does_not_write_runtime_config(tmp_path):
    env = os.environ.copy()
    env["CONTENT_PLATFORM_HOME"] = str(tmp_path / "runtime")
    result = subprocess.run(
        [sys.executable, "scripts/install.py", "--mode", "check"],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    combined = result.stdout + result.stderr
    assert "OPENAI_API_KEY=" not in combined
    assert "Cookie:" not in combined
    assert not (tmp_path / "runtime" / "config.json").exists()


def test_install_config_only_writes_runtime_report_and_policy_bounded_publishers(tmp_path):
    home = tmp_path / "runtime"
    env = os.environ.copy()
    env["CONTENT_PLATFORM_HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "scripts/install.py", "--mode", "config-only"],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0
    config_path = home / "config.json"
    report_path = home / "installation-report.json"
    assert config_path.exists()
    assert report_path.exists()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["generator"]["hermes_model"] == ""
    assert config["generator"]["allow_fallback"] is False
    assert config["workflow"]["require_unified_acceptance"] is True
    assert all(value == "enforce" for value in config["feature_flags"].values())
    platforms = config["publishers"]["platforms"]
    for platform in ["youtube", "tiktok", "reddit", "devto", "mastodon", "bluesky", "nostr"]:
        assert platform in platforms
    expected_routes = {
        "kuaishou": "social-auto-upload",
        "wechat": "wechat-draft",
        "weixin": "wechat-draft",
        "wechat_official": "wechat-draft",
        "zhihu": "zhihu-playwright",
        "juejin": "juejin-api",
        "twitter": "x-playwright",
        "x": "x-playwright",
        "bilibili": "manual-handoff",
        "douyin": "manual-handoff",
        "douyin_ai": "manual-handoff",
        "douyin_pet": "manual-handoff",
        "shipinhao": "manual-handoff",
        "xiaohongshu": "manual-handoff",
        "rednote": "manual-handoff",
        "youtube": "manual-handoff",
        "tiktok": "manual-handoff",
    }
    assert {name: platforms[name]["type"] for name in expected_routes} == expected_routes
    assert config["publishers"]["routing_defaults"]["domestic"]["type"] == "manual-handoff"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "config-only"
    assert Path(report["install_root"]) == home


def test_example_config_explicitly_routes_every_production_delivery_mode():
    config = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    platforms = config["publishers"]["platforms"]

    assert platforms["kuaishou"]["type"] == "social-auto-upload"
    assert all(platforms[name]["type"] == "wechat-draft" for name in ["wechat", "weixin", "wechat_official"])
    assert platforms["zhihu"]["type"] == "zhihu-playwright"
    assert platforms["juejin"]["type"] == "juejin-api"
    assert all(platforms[name]["type"] == "x-playwright" for name in ["twitter", "x"])
    manual = ["bilibili", "douyin", "douyin_ai", "douyin_pet", "shipinhao", "xiaohongshu", "rednote", "youtube", "tiktok"]
    assert all(platforms[name]["type"] == "manual-handoff" for name in manual)
    assert config["publishers"]["routing_defaults"]["domestic"]["type"] == "manual-handoff"
