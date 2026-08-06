import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.discover_public_profile_urls import main


def test_discovery_does_not_apply_unverified_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "collector.json"
        config.write_text(json.dumps({"douyin": {"state_file": "/private/douyin.json"}}), encoding="utf-8")
        with patch("scripts.discover_public_profile_urls._search_web", return_value=["https://www.douyin.com/user/test"]), patch(
            "scripts.discover_public_profile_urls.collect_platform_metrics",
            return_value={"platforms": {"douyin": {"status": "public_signal_unavailable"}}},
        ):
            code = main(["--collector-config", str(config), "--platform", "douyin", "--apply"])
        data = json.loads(config.read_text(encoding="utf-8"))
        assert code == 0
        assert "public_profile_url" not in data["douyin"]


def test_discovery_applies_verified_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "collector.json"
        config.write_text(json.dumps({"douyin": {"state_file": "/private/douyin.json"}}), encoding="utf-8")
        with patch("scripts.discover_public_profile_urls._search_web", return_value=["https://www.douyin.com/user/test?from=search"]), patch(
            "scripts.discover_public_profile_urls.collect_platform_metrics",
            return_value={"platforms": {"douyin": {"status": "public_signal", "account_metrics": {"followers": 12}}}},
        ):
            code = main(["--collector-config", str(config), "--platform", "douyin", "--apply"])
        data = json.loads(config.read_text(encoding="utf-8"))
        assert code == 0
        assert data["douyin"]["public_profile_url"] == "https://www.douyin.com/user/test"
