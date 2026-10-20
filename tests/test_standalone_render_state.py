import json

from content_platform.standalone_render_state import write_rendered_unverified


def test_standalone_renderer_is_not_publishable_without_unified_release(tmp_path):
    (tmp_path / "final.mp4").write_bytes(b"not-a-real-video")
    payload = write_rendered_unverified(tmp_path, platform="youtube_shorts", renderer="yt_shorts_render.py")
    saved = json.loads((tmp_path / "standalone_render_state.json").read_text())
    assert payload == saved
    assert saved["status"] == "rendered_unverified"
    assert saved["publishable"] is False
    assert saved["delivery_allowed"] is False
    assert saved["requires_unified_release"] is True
    assert saved["artifact_sha256"]