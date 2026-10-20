from __future__ import annotations

import hashlib
import json
from pathlib import Path

from content_platform.delivery_manifest import build_delivery_manifest
import pytest

def _trusted(video: Path, cover: Path, state: str) -> dict:
    gate_to_checker = {
        "DEDUP_GATED": "dedup",
        "MEDIA_GATED": "media",
        "VISUAL_GATED": "visual",
        "AUDIO_GATED": "audio",
        "COVER_GATED": "cover",
        "PACKAGE_GATED": "package",
    }
    checker_digests = {}
    for gate, checker in gate_to_checker.items():
        checker_payload = {"checker": checker, "verdict": "pass"}
        checker_digest = hashlib.sha256(
            json.dumps(checker_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        (video.parent / f"{checker}_checker_evidence.json").write_text(
            json.dumps({**checker_payload, "evidence_sha256": checker_digest}),
            encoding="utf-8",
        )
        checker_digests[gate] = checker_digest
    hashes = {
        "video": hashlib.sha256(video.read_bytes()).hexdigest(),
        "cover": hashlib.sha256(cover.read_bytes()).hexdigest(),
    }
    bundle = build_delivery_manifest(
        video.parent,
        required_paths=[video, cover, *[video.parent / f"{checker}_checker_evidence.json" for checker in gate_to_checker.values()]],
        identity={"run_id": "run-1", "revision": 1, "attempt_id": "attempt-1", "platform": "douyin_ai"},
    )
    (video.parent / "delivery_manifest.json").write_text(json.dumps(bundle), encoding="utf-8")
    (video.parent / "video_toolchain_runner_manifest.json").write_text(json.dumps({"ok": True, "artifact_set_sha256": bundle["artifact_set_sha256"]}), encoding="utf-8")
    return {
        "run_id": "run-1",
        "revision": 1,
        "attempt_id": "attempt-1",
        "state": state,
        "failure_reason": None,
        "artifacts": [
            {"name": "video", "path": str(video), "role": "OUTPUT"},
            {"name": "cover", "path": str(cover), "role": "OUTPUT"},
        ],
        "artifact_sha256": hashes,
        "artifact_set_sha256": bundle["artifact_set_sha256"],
        "gate_evidence": [
            {
                "gate": gate,
                "run_id": "run-1",
                "revision": 1,
                "attempt_id": "attempt-1",
                "artifact_sha256": hashes,
                "evidence_sha256": checker_digests[gate],
            }
            for gate in ("DEDUP_GATED", "MEDIA_GATED", "VISUAL_GATED", "AUDIO_GATED", "COVER_GATED", "PACKAGE_GATED")
        ],
    }


def test_media_bridge_rejects_legacy_rendered_when_trusted_run_is_not_handoff_ready(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(_trusted(video, cover, "RENDERED_UNVERIFIED")), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="HANDOFF_READY"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_rejects_handoff_without_dedup_gate_evidence(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    manifest = _trusted(video, cover, "HANDOFF_READY")
    manifest["gate_evidence"] = [
        item for item in manifest["gate_evidence"] if item["gate"] != "DEDUP_GATED"
    ]
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="gate evidence incomplete"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_rejects_dedup_gate_without_evidence_hash(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    manifest = _trusted(video, cover, "HANDOFF_READY")
    next(
        item for item in manifest["gate_evidence"] if item["gate"] == "DEDUP_GATED"
    )["evidence_sha256"] = None
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="dedup evidence hash"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_rejects_tampered_dedup_checker_evidence(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    checker = tmp_path / "dedup_checker_evidence.json"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    manifest = _trusted(video, cover, "HANDOFF_READY")
    next(
        item for item in manifest["gate_evidence"] if item["gate"] == "DEDUP_GATED"
    )["evidence_sha256"] = json.loads(checker.read_text(encoding="utf-8"))["evidence_sha256"]
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    checker.write_bytes(b"tampered-dedup-check")

    with pytest.raises(RuntimeError, match="delivery_file_hash_mismatch:dedup_checker_evidence.json"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_rejects_tampered_non_dedup_checker_evidence(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    manifest = _trusted(video, cover, "HANDOFF_READY")
    (tmp_path / "trusted_run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "visual_checker_evidence.json").write_bytes(b"tampered-visual-check")

    with pytest.raises(RuntimeError, match="delivery_file_hash_mismatch:visual_checker_evidence.json"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_rejects_user_no_go_even_when_manifest_is_handoff_ready(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    manifest = _trusted(video, cover, "HANDOFF_READY")
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / "user_visual_rejection.json").write_text(
        json.dumps(
            {
                "version": "user-visual-rejection-v1",
                "run_id": manifest["run_id"],
                "attempt_id": manifest["attempt_id"],
                "artifact_sha256": manifest["artifact_sha256"]["video"],
                "user_verdict": "NO_GO",
                "delivery_allowed": False,
                "upload_or_publish_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="delivery_extra_files"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_media_bridge_accepts_only_hash_current_handoff_ready_manifest(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    trusted_path = tmp_path / "trusted_run_manifest.json"
    trusted_path.write_text(json.dumps(_trusted(video, cover, "HANDOFF_READY")), encoding="utf-8")

    result = MediaBridge._validate_trusted_video_manifest(tmp_path)
    assert result["state"] == "HANDOFF_READY"

    video.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="hash"):
        MediaBridge._validate_trusted_video_manifest(tmp_path)


def test_required_video_toolchain_rejects_legacy_rendered_without_trusted_manifest(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    manifest = {
        "ok": True,
        "status": "rendered",
        "output": str(video),
        "selected_pipeline": "localized_repost_video",
        "repost_source": {"source_type": "local_source_video", "path": str(video)},
        "source_asset_match": {"passed": True, "mode": "local_source_video"},
        "toolchain_contract": {
            "planned_tools": [
                "source_video_discovery",
                "source_asset_matcher",
                "autoclip_adapter.run_autoclip_pipeline",
                "source_dedup_db",
                "ffmpeg.clip_segments",
                "ffmpeg.concat",
                "repost_rights_manifest",
            ]
        },
    }

    with pytest.raises(RuntimeError, match="trusted video manifest is missing"):
        MediaBridge._validate_required_video_toolchain_manifest(
            manifest,
            tmp_path,
            {"required": True, "selected_pipeline": "localized_repost_video"},
        )


def test_required_video_toolchain_rejects_output_not_bound_to_trusted_video(tmp_path: Path) -> None:
    from content_platform.media import MediaBridge

    trusted_video = tmp_path / "trusted.mp4"
    runner_video = tmp_path / "runner.mp4"
    cover = tmp_path / "cover.png"
    trusted_video.write_bytes(b"trusted-video")
    runner_video.write_bytes(b"different-video")
    cover.write_bytes(b"cover")
    (tmp_path / "trusted_run_manifest.json").write_text(
        json.dumps(_trusted(trusted_video, cover, "HANDOFF_READY")), encoding="utf-8"
    )
    manifest = {
        "ok": True,
        "status": "rendered",
        "output": str(runner_video),
        "selected_pipeline": "localized_repost_video",
        "repost_source": {"source_type": "local_source_video", "path": str(runner_video)},
        "source_asset_match": {"passed": True, "mode": "local_source_video"},
        "toolchain_contract": {
            "planned_tools": [
                "source_video_discovery",
                "source_asset_matcher",
                "autoclip_adapter.run_autoclip_pipeline",
                "source_dedup_db",
                "ffmpeg.clip_segments",
                "ffmpeg.concat",
                "repost_rights_manifest",
            ]
        },
    }

    with pytest.raises(RuntimeError, match="does not match trusted video"):
        MediaBridge._validate_required_video_toolchain_manifest(
            manifest,
            tmp_path,
            {"required": True, "selected_pipeline": "localized_repost_video"},
        )
