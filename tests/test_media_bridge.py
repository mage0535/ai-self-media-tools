from pathlib import Path

from content_platform.media import MediaBridge


def test_video_visual_assets_never_cycle_missing_images(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    bridge = MediaBridge({}, tmp_path)
    packet = bridge._prepare_video_visual_assets(
        {
            "platforms": ["kuaishou"],
            "artifacts": [
                {"kind": "image", "path": str(first)},
                {"kind": "image", "path": str(second)},
            ],
        },
        tmp_path / "output",
        {"selected_pipeline": "knowledge_card_video"},
    )

    assert packet["image_count"] == 2
    assert packet["scene_count"] == 2
    assert len(packet["assignments"]) == 2
    assert all(item["reused"] is False for item in packet["assignments"])
