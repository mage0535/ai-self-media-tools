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


def test_install_config_only_writes_runtime_report_and_international_publishers(tmp_path):
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
    platforms = config["publishers"]["platforms"]
    for platform in ["youtube", "tiktok", "reddit", "devto", "mastodon", "bluesky", "nostr"]:
        assert platform in platforms

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "config-only"
    assert Path(report["install_root"]) == home
