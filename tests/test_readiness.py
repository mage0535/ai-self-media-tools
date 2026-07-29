from unittest.mock import patch

from content_platform.readiness import inspect_delivery_readiness


def test_readiness_can_skip_expensive_social_cli_probe():
    config = {
        "skip_cli_probe": True,
        "publishers": {
            "platforms": {
                "douyin": {
                    "type": "social-auto-upload",
                    "project_dir": "/missing",
                    "python_bin": "/missing/python",
                }
            }
        },
    }

    with patch("content_platform.readiness.subprocess.run") as call:
        readiness = inspect_delivery_readiness(config)

    assert readiness["publishers"]["douyin"]["cli_probe"]["skipped"] is True
    assert readiness["tools"]["social_auto_upload"]["cli_probe"]["skipped"] is True
    call.assert_not_called()
