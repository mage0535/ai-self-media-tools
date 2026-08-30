import json
from pathlib import Path

from content_platform.agnes_provider import AgnesVideoProvider


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode()


def test_agnes_video_creates_polls_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", "test")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.data))
        if request.data:
            return Response({"video_id": "vid-1", "task_id": "task-1", "status": "queued"})
        return Response({"video_id": "vid-1", "status": "completed", "metadata": {"url": "https://cdn.test/video.mp4"}})

    monkeypatch.setattr("content_platform.agnes_provider.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("content_platform.agnes_provider._download", lambda _url, path: path.write_bytes(b"video"))
    provider = AgnesVideoProvider(poll_interval=0, timeout=5)
    output = tmp_path / "clip.mp4"

    result = provider.generate("camera push in", output, seconds=5, aspect_ratio="9:16")

    assert output.read_bytes() == b"video"
    create = json.loads(calls[0][1])
    assert create["model"] == "agnes-video-2.5-flash"
    assert create["size"] == "720P"
    assert create["seconds"] == "5"
    assert "video_id=vid-1" in calls[1][0]
    assert result["status"] == "completed"
    assert result["provider"] == "agnes"


def test_agnes_video_rejects_invalid_flash_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", "test")
    provider = AgnesVideoProvider()
    try:
        provider.generate("clip", tmp_path / "clip.mp4", seconds=20)
    except ValueError as exc:
        assert "4..12" in str(exc)
    else:
        raise AssertionError("invalid duration must fail before API call")
