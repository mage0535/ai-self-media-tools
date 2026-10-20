from pathlib import Path

from content_platform.delivery_manifest import build_delivery_manifest, validate_attempt_bundle


def _bundle(root: Path):
    (root / "final.mp4").write_bytes(b"video")
    manifest = build_delivery_manifest(
        root,
        required_paths=[root / "final.mp4"],
        identity={"run_id": "run-1", "attempt_id": "attempt-1", "platform": "douyin_ai"},
    )
    (root / "delivery_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
    (root / "video_toolchain_runner_manifest.json").write_text(__import__("json").dumps({"artifact_set_sha256": manifest["artifact_set_sha256"]}), encoding="utf-8")
    return manifest


def test_attempt_bundle_requires_exact_root_identity_and_runner(tmp_path: Path):
    manifest = _bundle(tmp_path)
    ok = validate_attempt_bundle(tmp_path, expected_identity={"run_id": "run-1", "attempt_id": "attempt-1"})
    assert ok["passed"] is True
    bad = validate_attempt_bundle(tmp_path, expected_identity={"attempt_id": "old-attempt"})
    assert bad["passed"] is False
    assert "identity_mismatch:attempt_id" in bad["failures"]
    (tmp_path / "video_toolchain_runner_manifest.json").write_text('{"artifact_set_sha256":"bad"}', encoding="utf-8")
    bad_runner = validate_attempt_bundle(tmp_path)
    assert bad_runner["passed"] is False
    assert "runner_artifact_set_mismatch" in bad_runner["failures"]
