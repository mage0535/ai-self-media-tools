from pathlib import Path

from content_platform.store import Store


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

    assert result["passed"] is True
    assert Path(result["artifacts_dir"]) == render


def test_acceptance_rejects_unverified_first_person_operational_claim(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    body = "# 标题\n\n" + ("我维护这条管线八个月，零事故。" * 240)
    job = store.create_job("真实长文", ["juejin"], {"platform_source_matrix": _real_matrix("juejin")})
    store.save_draft(job["id"], "标题", body, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})

    result = evaluate_job_acceptance(store, job["id"], "juejin")

    assert result["passed"] is False
    assert "unverified_first_person_operational_claim" in result["failures"]


def test_acceptance_allows_editorial_calendar_with_complete_evidence(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    body = "# 标题\n\n" + ("这是可执行的真实内容。" * 400)
    brief = {
        "selection_mode": "editorial_calendar",
        "editorial_evidence": {
            "strategy_source": "growth_strategy:juejin:latest",
            "calendar_column": "engineering",
            "planned_date": "2026-08-18",
            "dedupe": "7d_clear",
        },
    }
    job = store.create_job("编辑日历文章", ["juejin"], brief)
    store.save_draft(job["id"], "标题", body, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})

    result = evaluate_job_acceptance(store, job["id"], "juejin")

    assert result["passed"] is True


def test_acceptance_rejects_repeated_video_source_assets(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["bilibili"], {"platform_source_matrix": _real_matrix("bilibili")})
    store.save_draft(job["id"], "title", "body", "pass", {}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "artifacts" / job["id"]
    render.mkdir(parents=True)
    (render / "scene_manifest.json").write_text("{}", encoding="utf-8")
    (render / "tts_config.json").write_text("{}", encoding="utf-8")
    (render / "final.mp4").write_bytes(b"video")
    (render / "cover.png").write_bytes(b"cover")
    for index in range(4):
        path = render / f"section-{index}.png"
        path.write_bytes(b"same-image")
        store.add_artifact(job["id"], "image", str(path))

    result = evaluate_job_acceptance(store, job["id"], "bilibili", artifacts_dir=render)

    assert result["passed"] is False
    assert "duplicate_visual_assets" in result["failures"]


def test_acceptance_rejects_compliance_claims_without_sources(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    body = "# 标题\n\n" + ("这是一段内容。" * 400)
    job = store.create_job("真实长文", ["juejin"], {"platform_source_matrix": _real_matrix("juejin")})
    store.save_draft(
        job["id"], "标题", body, "pass",
        {"compliance": {"findings": [{"code": "numeric_claim_without_source"}]}},
        draft_meta={"quality_gate": {"passed": True}},
    )

    result = evaluate_job_acceptance(store, job["id"], "juejin")

    assert result["passed"] is False
    assert "unsupported_factual_claims" in result["failures"]
