import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image
import pytest


def _write_image(path: Path, color: tuple[int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1200, 900), color).save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_juejin_article_media_executes_four_real_assets_with_checkpointed_resume(tmp_path):
    from content_platform.adapters.media import execute_article_media

    calls = []
    failures = {"section-02"}

    def generate(item, output):
        calls.append(item["asset_id"])
        if item["asset_id"] in failures:
            failures.remove(item["asset_id"])
            raise RuntimeError("transient provider failure")
        colors = {
            "cover": (20, 40, 80),
            "section-01": (80, 40, 20),
            "section-02": (20, 80, 40),
            "section-03": (80, 20, 40),
        }
        checksum = _write_image(output, colors[item["asset_id"]])
        return {
            "source_url": f"https://source.example/{item['asset_id']}",
            "license": "generated_for_project",
            "semantic_match_score": 0.91,
            "match_reason": item["section"],
            "checksum": checksum,
        }

    result = execute_article_media(
        {
            "id": "j1",
            "platforms": ["juejin"],
            "topic": "可验证的媒体执行链",
            "title": "可验证的媒体执行链",
            "sections": ["问题", "方法", "验证"],
            "draft_meta": {"cover_design": {"layout_key": "hero_conflict", "safe_zone_verified": True}},
        },
        tmp_path,
        generate,
        public_staging_base_url="https://staging.example/media",
        max_concurrency=2,
        max_attempts=2,
    )

    assert len(result["assets"]) == 4
    assert len(result["section_image_map"]) == 3
    assert len({asset["checksum"] for asset in result["assets"]}) == 4
    assert len({asset["source_url"] for asset in result["assets"]}) == 4
    assert all(asset["public_url"].startswith("https://staging.example/media/j1/") for asset in result["assets"])
    assert result["editor_visible_mapping"][0]["asset_id"] == "section-01"
    assert result["cover_quality_evidence"]["safe_zone_verified"] is True
    assert json.loads((tmp_path / "asset_checkpoints.json").read_text(encoding="utf-8"))["section-02"]["attempts"] == 2

    calls_before_resume = len(calls)
    resumed = execute_article_media(
        {"id": "j1", "platforms": ["juejin"], "topic": "可验证的媒体执行链", "sections": ["问题", "方法", "验证"]},
        tmp_path,
        lambda *_: (_ for _ in ()).throw(AssertionError("checkpointed asset was regenerated")),
        public_staging_base_url="https://staging.example/media",
        max_concurrency=2,
        max_attempts=2,
    )
    assert len(calls) == calls_before_resume
    assert resumed["handoff_contract"]["version"]


def test_handoff_contract_rejects_artifact_existence_without_versioned_evidence(tmp_path):
    from content_platform.adapters.media import validate_handoff_contract

    media = tmp_path / "cover.png"
    _write_image(media, (1, 2, 3))
    artifact_only = {"state": "handoff_ready", "artifacts": [{"path": str(media)}]}
    rejected = validate_handoff_contract(artifact_only)
    assert rejected["passed"] is False
    assert "handoff_contract_version_missing" in rejected["failures"]
    assert "copy_media_version_missing" in rejected["failures"]
    assert "target_renderer_evidence_missing" in rejected["failures"]


def test_scene_manifest_requires_real_assets_and_observed_per_scene_evidence(tmp_path):
    from content_platform.adapters.media import validate_scene_manifest_contract

    scenes = []
    for index, color in enumerate(((1, 2, 3), (4, 5, 6)), 1):
        asset = tmp_path / f"scene-{index}.png"
        checksum = _write_image(asset, color)
        scenes.append(
            {
                "scene_id": f"s{index:02d}",
                "purpose": "show a matched implementation step",
                "asset": {"path": str(asset), "sha256": checksum, "source_url": f"https://source.example/{index}", "license": "CC BY 4.0"},
                "shot_language": "left_dolly",
                "subject_motion": "action_path",
                "text_motion": "label_stagger",
                "transition": "hard_cut",
                "rhythm": {"beat": "proof", "duration_seconds": 2.0},
                "interaction_cue": "save this step",
            }
        )
    manifest = {"version": "scene_manifest_v2", "timeline": [scene["scene_id"] for scene in scenes], "scenes": scenes}
    observed = {"s01": {"frame_difference": 0.12, "static_ratio": 0.2}, "s02": {"frame_difference": 0.11, "static_ratio": 0.3}}
    assert validate_scene_manifest_contract(manifest, observed=observed)["passed"] is True
    observed.pop("s02")
    result = validate_scene_manifest_contract(manifest, observed=observed)
    assert result["passed"] is False
    assert "scene_observation_missing:s02" in result["failures"]


def test_bgm_contract_is_online_real_instrument_and_7_day_unique():
    from content_platform.adapters.media import validate_bgm_contract

    good = {
        "source_url": "https://pixabay.com/music/acoustic-guitar/track",
        "license": "Pixabay Content License",
        "fingerprint": "bgm-unique",
        "real_instrument": True,
        "source": "pixabay_music",
    }
    assert validate_bgm_contract(good, recent_fingerprints={"old"})["passed"] is True
    assert validate_bgm_contract({**good, "source": "local_library"})["passed"] is False
    assert validate_bgm_contract({**good, "license": "CC BY-NC-ND 4.0"})["passed"] is False
    assert validate_bgm_contract({**good, "fingerprint": "old"}, recent_fingerprints={"old"})["passed"] is False


def test_tts_fingerprint_requires_nine_fields_and_compiled_pronunciation():
    from content_platform.adapters.media import build_tts_fingerprint, validate_tts_fingerprint

    fingerprint = build_tts_fingerprint(
        {"display_text": "Use AI", "tts_text": "Use A I", "unhandled_latin_tokens": []},
        provider="edge",
        voice="en-US",
        rate="+0%",
        sample_rate=44100,
        channels=2,
        duration_seconds=1.2,
        sha256="tts-sha",
    )
    assert len(fingerprint) == 9
    assert validate_tts_fingerprint(fingerprint)["passed"] is True
    assert validate_tts_fingerprint({**fingerprint, "unhandled_latin_tokens": ["API"]})["passed"] is False


def test_final_mp4_probe_requires_real_stereo_44100_audio_and_subtitles(tmp_path):
    from content_platform.adapters.media import probe_final_video

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for the real media fixture")
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nA real subtitle\n", encoding="utf-8")
    video = tmp_path / "final.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2", "-i", str(srt),
            "-map", "0:v", "-map", "1:a", "-map", "2:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-c:s", "mov_text", str(video),
        ],
        check=True,
    )
    result = probe_final_video(video)
    assert result["passed"] is True
    assert result["audio"]["sample_rate"] == 44100
    assert result["audio"]["channels"] == 2
    assert result["subtitle_streams"] == 1
