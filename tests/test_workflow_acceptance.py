import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_platform.run_contract import build_run_contract
from content_platform.store import Store


def _valid_cover(path: Path, size: tuple[int, int] = (1080, 1920)) -> Path:
    image = Image.new("RGB", size, "#071421")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 48):
        draw.rectangle((0, y, size[0], min(size[1] - 1, y + 47)), fill=(10, 30 + y // 96 % 35, 55))
    draw.ellipse((650, 500, 940, 790), fill="#ef8354", outline="white", width=12)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 88)
    draw.text((90, 260), "VERIFY FIRST", font=font, fill="white")
    image.save(path)
    return path


def _real_matrix(platform: str) -> dict:
    return {
        "platform": platform,
        "platform_internal_verified": True,
        "real_platform_collection_verified": True,
        "trend_evidence": {
            "source": f"{platform}_internal_search",
            "collected_at": "2026-08-16T00:00:00+00:00",
            "samples": [{"title": "real collected sample"}],
        },
    }


def test_acceptance_loads_real_long_form_body_from_job_and_persists_result(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    body = "# 标题\n\n> 一条真实证据。\n\n" + ("这是可执行的真实内容。" * 400) + "\n\n## 方法\n\n- 第一步\n- 第二步\n\n## 数据\n\n|项目|结果|\n|---|---|\n|测试|通过|\n\n### 复盘\n\n欢迎评论收藏。"
    job = store.create_job("真实长文", ["zhihu"], {"platform_source_matrix": _real_matrix("zhihu")})
    store.save_draft(job["id"], "标题", body, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})

    result = evaluate_job_acceptance(store, job["id"], "zhihu")

    assert result["passed"] is True
    assert result["body_source"] == "job.body"
    assert store.get_job(job["id"])["acceptance"]["passed"] is True


def test_acceptance_rejects_video_handoff_without_scene_or_tts_evidence(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["douyin_ai"], {"platform_source_matrix": _real_matrix("douyin_ai")})
    store.save_draft(job["id"], "标题", "你需要看到这个案例。" * 20, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "isolated-render-output" / job["id"]
    render.mkdir(parents=True)
    (render / "final.mp4").write_bytes(b"video")

    result = evaluate_job_acceptance(store, job["id"], "douyin_ai", artifacts_dir=render)

    assert result["passed"] is False
    assert "scene_manifest_missing" in result["failures"]
    assert "tts_config_missing" in result["failures"]


def test_xiaohongshu_card_note_is_not_asked_for_a_video(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("card", ["xiaohongshu"], {"platform_source_matrix": _real_matrix("xiaohongshu")})
    meta = {"quality_gate": {"passed": True}, "content_form": "manual_carousel"}
    store.save_draft(job["id"], "标题", "你需要看到这个案例。" * 20, "pass", {"level": "pass"}, draft_meta=meta)
    render = tmp_path / "render" / job["id"]
    render.mkdir(parents=True)
    _valid_cover(render / "cover.png")

    result = evaluate_job_acceptance(store, job["id"], "xiaohongshu", artifacts_dir=render)

    assert not {"video_missing", "scene_manifest_missing", "tts_config_missing"} & set(result["failures"])


def test_acceptance_uses_registered_video_and_cover_paths(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["douyin_ai"], {"platform_source_matrix": _real_matrix("douyin_ai")})
    store.save_draft(job["id"], "title", "body", "pass", {}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "artifacts" / job["id"]
    render.mkdir(parents=True)
    (render / "scene_manifest.json").write_text("{}", encoding="utf-8")
    (render / "tts_config.json").write_text("{}", encoding="utf-8")
    video = render / "rendered.mp4"
    cover = render / "custom-cover.png"
    video.write_bytes(b"video")
    cover.write_bytes(b"cover")
    store.add_artifact(job["id"], "video", str(video))
    store.add_artifact(job["id"], "cover", str(cover))

    result = evaluate_job_acceptance(store, job["id"], "douyin_ai")

    assert result["passed"] is False
    assert "video_runtime_gate_failed" in result["failures"]


def test_compiled_run_requires_passing_viral_cover_evidence(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["tiktok"], {
        "platform_source_matrix": _real_matrix("tiktok"),
        "run_contract": build_run_contract("tiktok"),
    })
    store.save_draft(job["id"], "title", "body", "pass", {}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "artifacts" / job["id"]
    render.mkdir(parents=True)
    (render / "scene_manifest.json").write_text("{}", encoding="utf-8")
    (render / "tts_config.json").write_text("{}", encoding="utf-8")
    (render / "final.mp4").write_bytes(b"video")
    cover = _valid_cover(render / "cover.png")
    background = _valid_cover(render / "background.png")

    missing = evaluate_job_acceptance(store, job["id"], "tiktok", artifacts_dir=render)
    assert "cover_quality_gate_failed" in missing["failures"]

    (render / "cover_quality_evidence.json").write_text(json.dumps({
        "platform": "tiktok", "layout_key": "hero_conflict", "hook": "VERIFY FIRST",
        "title_en": "VERIFY FIRST", "conflict_or_payoff": "verify first",
        "focal_subjects": ["cat", "dog"],
        "content_match_reason": "matches the script conflict",
        "background_provenance": {
            "path": str(background),
            "source": "test_fixture",
            "license": "test",
            "independent_render": True,
        },
        "cover_sha256": hashlib.sha256(cover.read_bytes()).hexdigest(),
        "safe_zone_verified": True, "degraded": False,
    }), encoding="utf-8")
    passed = evaluate_job_acceptance(store, job["id"], "tiktok", artifacts_dir=render)
    assert passed["passed"] is False
    assert "video_runtime_gate_failed" in passed["failures"]
    assert "asset_provenance_missing" in passed["failures"]


def test_compiled_run_rejects_duplicate_asset_provenance(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["tiktok"], {
        "platform_source_matrix": _real_matrix("tiktok"),
        "run_contract": build_run_contract("tiktok"),
    })
    store.save_draft(job["id"], "title", "body", "pass", {}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "artifacts" / job["id"]
    render.mkdir(parents=True)
    (render / "scene_manifest.json").write_text("{}", encoding="utf-8")
    (render / "tts_config.json").write_text("{}", encoding="utf-8")
    (render / "final.mp4").write_bytes(b"video")
    cover = render / "cover.jpg"
    Image.new("RGB", (1080, 1920), "navy").save(cover)
    (render / "cover_quality_evidence.json").write_text(
        '{"platform":"tiktok","layout_key":"hero_conflict","hook":"AI failed?",'
        '"conflict_or_payoff":"verify first","focal_subjects":["cat"],'
        '"content_match_reason":"matches script","safe_zone_verified":true,"degraded":false}', encoding="utf-8"
    )
    record = {
        "path": str(cover), "source_url": "https://example.test/cover", "license": "licensed",
        "semantic_match_score": 0.9, "match_reason": "matches script", "semantic_tags": ["AI"],
    }
    (render / "asset_provenance.json").write_text(__import__("json").dumps({"assets": [record, record]}), encoding="utf-8")

    result = evaluate_job_acceptance(store, job["id"], "tiktok", artifacts_dir=render)
    assert "asset_quality_gate_failed" in result["failures"]
