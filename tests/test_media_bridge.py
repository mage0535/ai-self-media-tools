from pathlib import Path

from content_platform.media import MediaBridge


def test_cover_generation_reuses_existing_verified_cover(tmp_path):
    output = tmp_path / "artifacts" / "job-1"
    output.mkdir(parents=True)
    cover = output / "cover.png"
    cover.write_bytes(b"verified-cover")
    bridge = MediaBridge({"cover": {"enabled": True}}, tmp_path)

    artifact = bridge.generate("cover", {"id": "job-1", "platforms": ["kuaishou"]})

    assert artifact["kind"] == "cover"
    assert artifact["path"] == str(cover)
    assert artifact["source"] == "existing_verified_image_artifact"


def test_video_visual_assets_never_cycle_missing_images(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    duplicate = tmp_path / "duplicate.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    duplicate.write_bytes(b"first")

    bridge = MediaBridge({}, tmp_path)
    packet = bridge._prepare_video_visual_assets(
        {
            "platforms": ["kuaishou"],
            "artifacts": [
                {"kind": "image", "path": str(first)},
                {"kind": "image", "path": str(second)},
                {"kind": "image", "path": str(duplicate)},
            ],
        },
        tmp_path / "output",
        {"selected_pipeline": "knowledge_card_video"},
    )

    assert packet["image_count"] == 2
    assert packet["scene_count"] == 2
    assert len(packet["assignments"]) == 2
    assert all(item["reused"] is False for item in packet["assignments"])
