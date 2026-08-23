from pathlib import Path
from unittest.mock import patch

from content_platform.media_canary import probe_media_artifact


def test_media_canary_requires_measured_av_and_quality_evidence(tmp_path: Path):
    (tmp_path / "final.mp4").write_bytes(b"video")
    for name in ("av_alignment_evidence.json", "audio_quality_evidence.json", "render_quality_evidence.json"):
        (tmp_path / name).write_text('{"passed": true}', encoding="utf-8")
    probe = {"streams": [{"codec_type": "video"}, {"codec_type": "audio", "sample_rate": "44100", "channels": 2}], "format": {"duration": "10"}}
    with patch("content_platform.media_canary._ffprobe", return_value=probe):
        result = probe_media_artifact(tmp_path)
    assert result["status"] == "artifact_verified"
    assert result["sha256"].startswith("sha256:")


def test_media_canary_fails_without_audio(tmp_path: Path):
    (tmp_path / "final.mp4").write_bytes(b"video")
    with patch("content_platform.media_canary._ffprobe", return_value={"streams": [{"codec_type": "video"}], "format": {"duration": "10"}}):
        result = probe_media_artifact(tmp_path)
    assert result["status"] == "failed"
    assert "audio_stream_missing" in result["failures"]
