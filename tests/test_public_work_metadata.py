import json

from content_platform.public_work_metadata import PublicWorkMetadataAdapter


def test_public_work_metadata_emits_auditable_youtube_snapshot_without_credentials():
    seen = []

    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": json.dumps({
            "id": "Uc7jZAoiWwk", "webpage_url": "https://www.youtube.com/watch?v=Uc7jZAoiWwk",
            "title": "AI辅助设备运维", "channel": "Factory AI", "upload_date": "20260513",
            "view_count": 101, "like_count": 9, "comment_count": 2, "duration": 60,
            "extractor_key": "Youtube",
        }), "stderr": ""})()

    report = PublicWorkMetadataAdapter(runner=runner).collect(platform="youtube", urls=["https://www.youtube.com/watch?v=Uc7jZAoiWwk"])
    row = report["items"][0]
    assert row["content_id"] == "Uc7jZAoiWwk"
    assert row["published_at"] == "2026-05-13"
    assert row["metrics"] == {"views": 101, "likes": 9, "comments": 2}
    assert row["native_verified"] is True
    assert row["generation_only"] is True
    assert row["auto_selection_eligible"] is False
    command, kwargs = seen[0]
    assert command[:5] == ["yt-dlp", "--skip-download", "--no-playlist", "--no-warnings", "--dump-single-json"]
    assert not any("cookie" in part.casefold() or "proxy" in part.casefold() for part in command)
    assert kwargs["timeout"] == 45


def test_public_work_metadata_rejects_cross_platform_url_before_execution():
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True

    report = PublicWorkMetadataAdapter(runner=runner).collect(platform="youtube", urls=["https://example.com/watch?v=x"])
    assert report["items"] == []
    assert report["sources"][0]["status"] == "rejected"
    assert called is False
