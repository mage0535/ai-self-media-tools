import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

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
        public_staging_verifier=lambda url: {"passed": True, "status": 200, "url": url},
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
        public_staging_verifier=lambda url: {"passed": True, "status": 200, "url": url},
        max_concurrency=2,
        max_attempts=2,
    )
    assert len(calls) == calls_before_resume
    assert resumed["handoff_contract"]["version"]


def test_juejin_content_route_cannot_bypass_production_four_asset_path(tmp_path, monkeypatch):
    from content_platform.media import MediaBridge

    bridge = MediaBridge({"image": {"enabled": True, "public_staging_base_url": "https://staging.example/media"}}, tmp_path)
    execute = Mock(
        return_value={
            "assets": [
                {"asset_id": "cover", "role": "cover", "path": str(tmp_path / "cover.png"), "checksum": "c", "public_url": "https://staging.example/media/j1/cover.png"},
                *[
                    {"asset_id": f"section-{i:02d}", "role": "section", "path": str(tmp_path / f"section-{i:02d}.png"), "checksum": str(i), "public_url": f"https://staging.example/media/j1/section-{i:02d}.png"}
                    for i in range(1, 4)
                ],
            ],
            "section_image_map": [{"asset_id": f"section-{i:02d}", "section": f"s{i}", "image": str(tmp_path / f"section-{i:02d}.png"), "public_url": f"https://staging.example/media/j1/section-{i:02d}.png"} for i in range(1, 4)],
            "article_media_contract": "contract.json",
        }
    )
    monkeypatch.setattr("content_platform.media.execute_article_media", execute)
    monkeypatch.setattr("content_platform.media.agent_scripts_dir", lambda: tmp_path)
    provider = Mock()
    monkeypatch.setattr(bridge.registry, "choose_provider", lambda kind: provider)

    result = bridge._generate_image(
        {
            "id": "j1",
            "title": "Juejin article",
            "topic": "Juejin article",
            "body": "body",
            "platforms": ["juejin"],
            "sections": ["s1", "s2", "s3"],
            "visual_route": {"auto": True, "route_order": ["content-driven-cards"]},
        },
        tmp_path / "artifacts" / "j1",
        {"enabled": True, "public_staging_base_url": "https://staging.example/media"},
    )

    assert len(result["images"]) == 4
    assert result["images"][0]["role"] == "cover"
    assert "auto_route" not in result
    execute.assert_called_once()


def test_article_media_records_staging_failure_and_fails_closed(tmp_path):
    from content_platform.adapters.media import execute_article_media

    def generate(item, output):
        checksum = _write_image(output, (20 + sum(ord(char) for char in item["asset_id"]) % 180, 40, 80))
        return {"source_url": f"https://source.example/{item['asset_id']}", "license": "generated_for_project", "checksum": checksum}

    with pytest.raises(RuntimeError, match="public_staging_verification_failed"):
        execute_article_media(
            {"id": "j2", "title": "Article", "sections": ["one", "two", "three"]},
            tmp_path,
            generate,
            public_staging_base_url="https://staging.example/media",
            public_staging_verifier=lambda url: {"passed": False, "status": 503, "url": url},
        )

    contract = json.loads((tmp_path / "article_media_contract.json").read_text(encoding="utf-8"))
    assert contract["handoff_contract"]["public_staging_evidence"]["passed"] is False


def test_juejin_publisher_requires_renderer_visibility_response(tmp_path):
    from content_platform.juejin_publisher import JuejinPublisher

    job = {
        "id": "j3",
        "title": "A Juejin article with a complete media package",
        "body": "problem\n\n![problem]()\n\ncase\n\n![case]()\n\nmethod\n\n![method]()\n\n" + ("A verified article paragraph with enough content. " * 60),
        "artifacts": [
            {"kind": "cover", "url": "https://cdn.example/cover.jpg"},
            *[{"kind": "image", "url": f"https://cdn.example/inline-{i}.jpg"} for i in range(3)],
        ],
        "draft_meta": {
            "section_image_map": [
                {"section": "problem", "image": "inline-0.jpg", "purpose": "show problem", "adjacent_to_text": True},
                {"section": "case", "image": "inline-1.jpg", "purpose": "show case", "adjacent_to_text": True},
                {"section": "method", "image": "inline-2.jpg", "purpose": "show method", "adjacent_to_text": True},
            ],
            "visual_template_selection": {"selected": "case_story_v1"},
        },
    }
    publisher = JuejinPublisher()
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_api", return_value={"err_no": 0, "data": {"id": "draft-3"}}
    ) as api:
        result = publisher.deliver(job, "juejin")

    assert result.ok is False
    assert result.status == "blocked"
    assert "editor visibility" in result.error
    payload = api.call_args.args[1]
    assert payload["cover_image"] == "https://cdn.example/cover.jpg"
    assert all(url in payload["mark_content"] for url in [f"https://cdn.example/inline-{i}.jpg" for i in range(3)])


def test_pipeline_final_gate_calls_task6_media_validators_fail_closed(tmp_path):
    from content_platform.adapters.media import build_tts_fingerprint
    from content_platform.pipeline import Pipeline
    from content_platform.store import Store

    store = Store(tmp_path / "state.db")
    store.init()
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "feature_flags": {"channel_auto_workflow_gate": "enforce"}})
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    draft = {
        "title": "Verified video",
        "body": "A rendered video with evidence.",
        "draft_meta": {
            "strategy": {"primary_platforms": ["douyin"]},
            "content_form": "short_video",
            "video_toolchain_plan": {"required": True},
            "video_artifact": {"path": str(video)},
            "scene_manifest": {"version": "scene_manifest_v2", "timeline": [], "scenes": []},
            "observed_scene_evidence": {},
            "bgm_source": {},
            "tts_fingerprint": build_tts_fingerprint({"display_text": "x", "tts_text": "x"}, provider="edge", voice="v", rate="0", sample_rate=44100, channels=2, duration_seconds=1, sha256="x"),
        },
    }
    rejected = {"passed": False, "failures": ["missing_evidence"]}
    with patch("content_platform.pipeline.validate_handoff_contract", return_value=rejected) as handoff, patch(
        "content_platform.pipeline.validate_scene_manifest_contract", return_value=rejected
    ) as scene, patch("content_platform.pipeline.validate_bgm_contract", return_value=rejected) as bgm, patch(
        "content_platform.pipeline.validate_tts_fingerprint", return_value=rejected
    ) as tts, patch("content_platform.pipeline.probe_final_video", return_value=rejected) as ffprobe:
        gate = pipeline._quality_gate("job-1", draft, {"level": "pass"}, {"score": 80}, phase="rendered")

    assert gate["passed"] is False
    assert "G6_media_contracts" in gate["gates"]
    assert gate["gates"]["G6_media_contracts"]["passed"] is False
    scene.assert_called_once()
    bgm.assert_called_once()
    tts.assert_called_once()
    ffprobe.assert_called_once()


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
