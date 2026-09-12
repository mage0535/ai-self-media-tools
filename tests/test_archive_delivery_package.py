from scripts.archive_delivery_package import archive_delivery_package_direct


def test_direct_archive_accepts_package_root_outside_repository(tmp_path):
    package = tmp_path / "artifacts" / "job-123"
    render = package / "render"
    render.mkdir(parents=True)
    (render / "final.mp4").write_bytes(b"video")
    (render / "scene_manifest.json").write_text('{"scenes": []}', encoding="utf-8")

    result = archive_delivery_package_direct(package)

    assert result["platform"] == "artifacts"
    assert (package / "final.mp4").read_bytes() == b"video"
    assert (package / "scene_manifest.json").is_file()
    assert "final.mp4 <- render/final.mp4" in result["copied"]
    assert all(str(tmp_path) not in row for row in result["copied"])


def test_direct_archive_preserves_legacy_platform_date_render_layout(tmp_path):
    render = tmp_path / "local_ops_youtube" / "20260912" / "render"
    render.mkdir(parents=True)
    (render / "final.mp4").write_bytes(b"video")

    result = archive_delivery_package_direct(render)

    assert result["platform"] == "youtube"
    assert (render.parent / "final.mp4").read_bytes() == b"video"
    assert "final.mp4 <- render/final.mp4" in result["copied"]
