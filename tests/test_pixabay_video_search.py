import json
from pathlib import Path
from unittest.mock import patch


def test_pixabay_video_search_downloads_local_mp4_and_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-key")
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    payload = b"\x00\x00\x00\x18ftyp" + b"x" * 5000
    api_calls = []

    class Response:
        def __init__(self, body, content_type="application/json"):
            self.body = body
            self.headers = {"Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return self.body

    body = {
        "total": 1,
        "totalHits": 1,
        "hits": [{
            "id": 123,
            "pageURL": "https://pixabay.com/videos/id-123/",
            "tags": "workflow, technology",
            "duration": 8,
            "user": "Example User",
            "videos": {
                "medium": {
                    "url": "https://cdn.pixabay.com/video/example_medium.mp4",
                    "width": 1280,
                    "height": 720,
                    "size": len(payload),
                    "thumbnail": "https://cdn.pixabay.com/video/example_medium.jpg",
                }
            },
        }],
    }

    def fake_urlopen(request, timeout):
        if "/api/videos/" in request.full_url:
            api_calls.append(request.full_url)
            assert "key=pixabay-key" in request.full_url
            return Response(json.dumps(body).encode())
        assert request.full_url.endswith("download=1")
        return Response(payload, "video/mp4")

    with patch("scripts.pixabay_video_search.urllib.request.urlopen", side_effect=fake_urlopen):
        from scripts.pixabay_video_search import search_videos

        records = search_videos("workflow technology", output_dir=tmp_path / "videos")

    assert len(records) == 1
    record = records[0]
    path = Path(record["path"])
    assert path.is_file()
    assert path.read_bytes() == payload
    assert record["provider"] == "pixabay"
    assert record["kind"] == "stock_video"
    assert record["license"] == "Pixabay Content License"
    assert record["source_url"] == "https://pixabay.com/videos/id-123/"
    assert record["duration"] == 8.0
    assert record["dimensions"] == {"width": 1280, "height": 720}
    assert len(api_calls) == 1


def test_stock_video_route_resolves_runtime_pixabay_adapter():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("stock_video", content_form="short_video", free_only=True)

    assert route[0]["source"] == "pixabay_video"
    assert route[0]["selectable"] is True
    assert route[0]["adapter"] == "scripts/pixabay_video_search.py"


def test_pixabay_capability_registry_points_to_image_and_video_adapters():
    registry = json.loads(Path("config/creative_capability_registry.json").read_text(encoding="utf-8"))
    rows = [row for row in registry["capabilities"] if row.get("source") in {"Pixabay", "Pixabay Video"}]

    assert any(row["adapter"] == "scripts/pixabay_image_search.py" for row in rows)
    assert any(row["adapter"] == "scripts/pixabay_video_search.py" for row in rows)
