from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch


def _manifest(video: Path, cover: Path) -> dict:
    hashes = {
        "video": hashlib.sha256(video.read_bytes()).hexdigest(),
        "cover": hashlib.sha256(cover.read_bytes()).hexdigest(),
    }
    gates = ["MEDIA_GATED", "VISUAL_GATED", "AUDIO_GATED", "COVER_GATED", "PACKAGE_GATED"]
    return {
        "run_id": "run-delivery",
        "revision": 1,
        "attempt_id": "attempt-1",
        "state": "HANDOFF_READY",
        "artifacts": [
            {"name": "video", "path": str(video), "role": "OUTPUT"},
            {"name": "cover", "path": str(cover), "role": "OUTPUT"},
        ],
        "artifact_sha256": hashes,
        "gate_evidence": [
            {
                "gate": gate,
                "run_id": "run-delivery",
                "revision": 1,
                "attempt_id": "attempt-1",
                "artifact_sha256": hashes,
            }
            for gate in gates
        ],
    }


def test_delivery_blocks_untrusted_mp4_before_any_send(tmp_path: Path) -> None:
    from scripts.deliver_media import deliver

    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    with patch("scripts.deliver_media.resolve_target", return_value="telegram:test"), patch(
        "scripts.deliver_media._send"
    ) as send:
        result = deliver("caption", [str(video)])
    assert result["passed"] is False
    assert result["error"] == "trusted_video_manifest_missing"
    send.assert_not_called()


def test_delivery_blocks_video_hash_drift_before_any_send(tmp_path: Path) -> None:
    from scripts.deliver_media import deliver

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video-v1")
    cover.write_bytes(b"cover")
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(_manifest(video, cover)), encoding="utf-8"
    )
    video.write_bytes(b"video-v2")
    with patch("scripts.deliver_media.resolve_target", return_value="telegram:test"), patch(
        "scripts.deliver_media._send"
    ) as send:
        result = deliver("caption", [str(video)])
    assert result["passed"] is False
    assert result["error"] == "trusted_video_preflight_failed"
    send.assert_not_called()
