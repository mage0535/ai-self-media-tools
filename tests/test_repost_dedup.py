import json
from pathlib import Path


def _history(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
    return path


def test_build_evidence_writes_complete_atomic_pass_document(tmp_path, monkeypatch):
    from content_platform import repost_dedup

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    history = _history(tmp_path / "history.jsonl", [])
    output = tmp_path / "dedup_evidence.json"
    monkeypatch.setattr(
        repost_dedup,
        "fingerprint_video",
        lambda path: {
            "sha256": "a" * 64,
            "frame_phashes": ["0000000000000000", "ffffffffffffffff"],
            "audio_fingerprint": "b" * 64,
            "audio_algorithm": "pcm_s16le_8khz_mono_sha256",
        },
    )

    evidence = repost_dedup.build_dedup_evidence(
        source,
        source_identity={"source_id": "provider:video-1", "source_uri": "https://example.test/video-1"},
        history_index=history,
        transform={"kind": "localized_caption_edit", "description": "Chinese captions and editorial cuts"},
        rights={"basis": "licensed", "reference": "license-42"},
        output_path=output,
    )

    assert evidence["passed"] is True
    assert evidence["source_identity"]["source_id"] == "provider:video-1"
    assert evidence["fingerprints"]["sha256"] == "a" * 64
    assert evidence["fingerprints"]["frame_phashes"]
    assert evidence["fingerprints"]["audio_fingerprint"] == "b" * 64
    assert evidence["history_index"]["status"] == "available"
    assert evidence["transform"]["kind"] == "localized_caption_edit"
    assert evidence["rights"]["basis"] == "licensed"
    assert json.loads(output.read_text(encoding="utf-8")) == evidence
    assert not list(tmp_path.glob(".dedup_evidence.json.*"))


def test_history_unavailable_fails_closed_and_still_writes_evidence(tmp_path, monkeypatch):
    from content_platform import repost_dedup

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "dedup_evidence.json"
    monkeypatch.setattr(
        repost_dedup,
        "fingerprint_video",
        lambda path: {
            "sha256": "a" * 64,
            "frame_phashes": ["0" * 16],
            "audio_fingerprint": "b" * 64,
            "audio_algorithm": "pcm_s16le_8khz_mono_sha256",
        },
    )

    evidence = repost_dedup.build_dedup_evidence(
        source,
        source_identity={"source_id": "provider:video-1", "source_uri": "https://example.test/video-1"},
        history_index=tmp_path / "missing.jsonl",
        transform={"kind": "localized_caption_edit", "description": "Chinese captions"},
        rights={"basis": "licensed", "reference": "license-42"},
        output_path=output,
    )

    assert evidence["passed"] is False
    assert evidence["history_index"]["status"] == "unavailable"
    assert "history_index_unavailable" in evidence["failures"]
    assert output.is_file()


def test_high_phash_similarity_or_missing_policy_fields_fail_closed(tmp_path, monkeypatch):
    from content_platform import repost_dedup

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    history = _history(
        tmp_path / "history.jsonl",
        [
            {
                "source_identity": {"source_id": "account:old"},
                "fingerprints": {
                    "sha256": "c" * 64,
                    "frame_phashes": ["0000000000000001"],
                    "audio_fingerprint": "d" * 64,
                },
            }
        ],
    )
    monkeypatch.setattr(
        repost_dedup,
        "fingerprint_video",
        lambda path: {
            "sha256": "a" * 64,
            "frame_phashes": ["0000000000000000"],
            "audio_fingerprint": "b" * 64,
            "audio_algorithm": "pcm_s16le_8khz_mono_sha256",
        },
    )

    duplicate = repost_dedup.build_dedup_evidence(
        source,
        source_identity={"source_id": "provider:new", "source_uri": "https://example.test/new"},
        history_index=history,
        transform={"kind": "localized_caption_edit", "description": "Chinese captions"},
        rights={"basis": "licensed", "reference": "license-42"},
        output_path=tmp_path / "duplicate.json",
    )
    missing_rights = repost_dedup.build_dedup_evidence(
        source,
        source_identity={"source_id": "provider:new", "source_uri": "https://example.test/new"},
        history_index=_history(tmp_path / "empty.jsonl", []),
        transform={"kind": "localized_caption_edit", "description": "Chinese captions"},
        rights={},
        output_path=tmp_path / "missing.json",
    )

    assert duplicate["passed"] is False
    assert duplicate["similarity"]["max_frame_similarity"] > 0.9
    assert "historical_similarity_match" in duplicate["failures"]
    assert missing_rights["passed"] is False
    assert "rights_missing" in missing_rights["failures"]


def test_fingerprint_video_extracts_sha_sampled_phash_and_audio(tmp_path):
    import subprocess

    from content_platform.repost_dedup import fingerprint_video

    video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x64:rate=8:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=8000:duration=1",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )

    result = fingerprint_video(video)

    assert len(result["sha256"]) == 64
    assert result["frame_phashes"]
    assert all(len(value) == 16 for value in result["frame_phashes"])
    assert len(result["audio_fingerprint"]) == 64
    assert result["frame_sample_count"] >= 1


def test_post_render_evidence_binds_top_level_final_mp4_sha256(tmp_path, monkeypatch):
    from content_platform import repost_dedup

    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"rendered-video")
    history = _history(tmp_path / "history.jsonl", [])
    output = tmp_path / "dedup_evidence.json"
    rendered_fingerprints = {
        "sha256": "f" * 64,
        "frame_phashes": ["0123456789abcdef"],
        "audio_fingerprint": "b" * 64,
        "audio_algorithm": "pcm_s16le_8khz_mono_sha256",
    }
    monkeypatch.setattr(
        repost_dedup,
        "fingerprint_video",
        lambda path: dict(rendered_fingerprints),
    )

    evidence = repost_dedup.build_dedup_evidence(
        candidate,
        source_identity={
            "source_id": "provider:video-1",
            "source_uri": "https://example.test/video-1",
        },
        history_index=history,
        transform={
            "kind": "localized_caption_edit",
            "description": "Chinese captions and editorial cuts",
        },
        rights={"basis": "licensed", "reference": "license-42"},
        output_path=output,
        stage="post_render",
        pre_render_fingerprints={
            "sha256": "a" * 64,
            "frame_phashes": ["0123456789abcdef"],
            "audio_fingerprint": "c" * 64,
        },
    )

    assert evidence["passed"] is True
    assert evidence["stage"] == "post_render"
    assert evidence["final_mp4_sha256"] == rendered_fingerprints["sha256"]
    assert json.loads(output.read_text(encoding="utf-8"))["final_mp4_sha256"] == rendered_fingerprints["sha256"]
