import json

import pytest

from content_platform.video_preflight import VideoPreflightError, validate_video_preflight


def _payload():
    return {
        "platform": "douyin_pet",
        "research_pack": {"attempted_sources": 5, "successful_sources": 3, "degraded_source": True},
        "topic_selection": {"selected": True, "reason": "platform-specific evidence"},
        "content_brief": {"hook": "猫咪行为观察"},
        "asset_plan": {"source": "fresh_generated_assets"},
        "quality_gates": {"allow_render": True},
    }


def test_preflight_blocks_degraded_research_by_default(tmp_path):
    (tmp_path / "video_preflight.json").write_text(json.dumps(_payload()), encoding="utf-8")
    with pytest.raises(VideoPreflightError, match="research_native_evidence_required"):
        validate_video_preflight(tmp_path, "douyin_pet")


def test_preflight_accepts_degraded_research_only_with_explicit_override(tmp_path):
    payload = _payload()
    payload["allow_degraded_render"] = True
    (tmp_path / "video_preflight.json").write_text(json.dumps(payload), encoding="utf-8")
    assert validate_video_preflight(tmp_path, "douyin_pet")["platform"] == "douyin_pet"


def test_preflight_blocks_missing_research(tmp_path):
    with pytest.raises(VideoPreflightError, match="video_preflight.json missing"):
        validate_video_preflight(tmp_path, "douyin_pet")


def test_preflight_blocks_weak_sources_and_uncommitted_topic(tmp_path):
    payload = _payload()
    payload["research_pack"]["attempted_sources"] = 2
    payload["topic_selection"]["selected"] = False
    (tmp_path / "video_preflight.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VideoPreflightError, match="below_5.*topic_selection_not_committed"):
        validate_video_preflight(tmp_path, "douyin_pet")

def _overnight_payload(**research):
    payload = _payload()
    payload["version"] = "overnight_video_preflight_v1"
    payload["research_pack"] = {"attempted_sources": 18, "successful_sources": 17, "platform_native_verified": False,
                                "evidence_scope": "cross_platform", "cross_platform_source": "bilibili",
                                "hot_viral_sample_count": 3, **research}
    return payload


def test_preflight_accepts_labelled_cross_platform_overnight_research(tmp_path):
    (tmp_path / "video_preflight.json").write_text(json.dumps(_overnight_payload()), encoding="utf-8")
    assert validate_video_preflight(tmp_path, "douyin_pet")["research_pack"]["cross_platform_source"] == "bilibili"


@pytest.mark.parametrize("research", [{"cross_platform_source": ""}, {"hot_viral_sample_count": 0},
                                      {"evidence_scope": "shared_trend"}])
def test_preflight_rejects_unlabelled_or_empty_cross_platform_research(tmp_path, research):
    (tmp_path / "video_preflight.json").write_text(json.dumps(_overnight_payload(**research)), encoding="utf-8")
    with pytest.raises(VideoPreflightError, match="research_native_evidence_required"):
        validate_video_preflight(tmp_path, "douyin_pet")


def test_overnight_binder_writes_receipted_preflight_from_benchmark_matrix(tmp_path):
    from content_platform.store import Store
    from content_platform.workflow_runtime import WorkflowStepRunner
    from content_platform.video_preflight_inputs import bind_overnight_video_preflight, materialize_video_preflight
    store = Store(tmp_path / "state.db")
    job = store.create_job("同时拥有两只高智商猫的弊端", ["douyin_pet"])
    runner = WorkflowStepRunner(store, "wf_" + job["id"], job["id"])
    for name, output in {"run_content_hygiene": {"status": "pass"}, "generate_content": {"ok": True},
                         "validate_factual_claims": {"passed": True}, "run_safety_gate": {"level": "pass"},
                         "run_quality_gate": {"passed": True}}.items():
        runner.succeeded(name, output)
    brief = {"platform_source_matrix": {"platform": "douyin_pet", "evidence_scope": "cross_platform", "candidate_source": "bilibili",
                                        "sources_attempted": 18, "sources_succeeded": 17, "platform_fit_reason": "same genre"},
             "hot_viral_samples": [{"title": "x"}], "content_blueprint": {"selected_topic": job["topic"]}}
    ref = bind_overnight_video_preflight(store, job, "douyin_pet", brief, {}, "第一句\n\n第二句")
    out = tmp_path / "render"
    out.mkdir()
    materialize_video_preflight(store, dict(job, platforms=["douyin_pet"]), {"video_preflight_ref": ref}, "第一句\n\n第二句", out)
    assert json.loads((out / "video_preflight.json").read_text())["quality_gates"]["allow_render"] is True
    with pytest.raises(ValueError, match="native_preflight_render_inputs_changed"):
        materialize_video_preflight(store, dict(job, platforms=["douyin_pet"]), {"video_preflight_ref": ref}, "改过的脚本", tmp_path)


def test_overnight_binder_pins_the_voice_plan_source_for_the_renderer(tmp_path):
    from content_platform.store import Store
    from content_platform.workflow_runtime import WorkflowStepRunner
    from content_platform.video_preflight_inputs import bind_overnight_video_preflight
    store = Store(tmp_path / "state.db")
    job = store.create_job("同时拥有两只高智商猫的弊端", ["douyin_pet"])
    runner = WorkflowStepRunner(store, "wf_" + job["id"], job["id"])
    for name, output in {"run_content_hygiene": {"status": "pass"}, "generate_content": {"ok": True},
                         "validate_factual_claims": {"passed": True}, "run_safety_gate": {"level": "pass"},
                         "run_quality_gate": {"passed": True}}.items():
        runner.succeeded(name, output)
    brief = {"platform_source_matrix": {"platform": "douyin_pet", "evidence_scope": "platform_native",
                                        "sources_attempted": 6, "sources_succeeded": 5},
             "hot_viral_samples": [{"title": "x"}], "content_blueprint": {"selected_topic": job["topic"]}}
    ref = bind_overnight_video_preflight(store, job, "douyin_pet", brief, {}, "第一句\n\n第二句",
                                         {"path": "/abs/plan.json", "sha256": "a" * 64})
    payload = json.loads(open(ref["path"], encoding="utf8").read())
    assert payload["content_brief"]["video_source_planning"]["voice_plan_source"] == {"path": "/abs/plan.json", "sha256": "a" * 64}
    assert "video_source_planning" not in brief["content_blueprint"]
