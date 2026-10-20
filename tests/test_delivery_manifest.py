from __future__ import annotations

from pathlib import Path

from content_platform.delivery_manifest import (
    build_delivery_manifest,
    validate_attempt_bundle,
    validate_delivery_manifest,
)


def test_delivery_manifest_binds_exact_file_set_and_hash(tmp_path: Path):
    (tmp_path / "final.mp4").write_bytes(b"video")
    (tmp_path / "cover.png").write_bytes(b"cover")
    manifest = build_delivery_manifest(
        tmp_path,
        required_paths=[tmp_path / "final.mp4", tmp_path / "cover.png"],
        identity={"run_id": "r1", "attempt_id": "a1", "platform": "douyin_ai"},
    )

    assert validate_delivery_manifest(tmp_path, manifest)["passed"] is True

    (tmp_path / "extra.txt").write_text("unexpected", encoding="utf-8")
    failed = validate_delivery_manifest(tmp_path, manifest)
    assert failed["passed"] is False
    assert "delivery_extra_files" in failed["failures"]


def test_delivery_manifest_rejects_replaced_candidate(tmp_path: Path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"video-v1")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"cover")
    manifest = build_delivery_manifest(
        tmp_path,
        required_paths=[final, cover],
        identity={"run_id": "r1", "attempt_id": "a1", "platform": "douyin_ai"},
    )

    final.write_bytes(b"video-v2")
    failed = validate_delivery_manifest(tmp_path, manifest)
    assert failed["passed"] is False
    assert "delivery_file_hash_mismatch:final.mp4" in failed["failures"]
