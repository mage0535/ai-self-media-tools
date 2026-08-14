from pathlib import Path

from content_platform.store import Store


def test_acceptance_loads_real_long_form_body_from_job_and_persists_result(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    body = "# 标题\n\n> 一条真实证据。\n\n" + ("这是可执行的真实内容。" * 400) + "\n\n## 方法\n\n- 第一步\n- 第二步\n\n## 数据\n\n|项目|结果|\n|---|---|\n|测试|通过|\n\n### 复盘\n\n欢迎评论收藏。"
    job = store.create_job("真实长文", ["zhihu"], {"platform_source_matrix": {"platform_internal_verified": True}})
    store.save_draft(job["id"], "标题", body, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})

    result = evaluate_job_acceptance(store, job["id"], "zhihu")

    assert result["passed"] is True
    assert result["body_source"] == "job.body"
    assert store.get_job(job["id"])["acceptance"]["passed"] is True


def test_acceptance_rejects_video_handoff_without_scene_or_tts_evidence(tmp_path: Path):
    from content_platform.workflow_acceptance import evaluate_job_acceptance

    store = Store(tmp_path / "state.db")
    job = store.create_job("video", ["douyin_ai"], {"platform_source_matrix": {"platform_internal_verified": True}})
    store.save_draft(job["id"], "标题", "你需要看到这个案例。" * 20, "pass", {"level": "pass"}, draft_meta={"quality_gate": {"passed": True}})
    render = tmp_path / "artifacts" / job["id"]
    render.mkdir(parents=True)
    (render / "final.mp4").write_bytes(b"video")

    result = evaluate_job_acceptance(store, job["id"], "douyin_ai", artifacts_dir=render)

    assert result["passed"] is False
    assert "scene_manifest_missing" in result["failures"]
    assert "tts_config_missing" in result["failures"]
