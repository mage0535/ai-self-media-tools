import json
import tempfile
from pathlib import Path

from content_platform.pipeline import Pipeline
from content_platform.store import Store


def _pipeline(root: Path) -> Pipeline:
    store = Store(root / "state.db")
    store.init()
    return Pipeline(store, {
        "data_dir": str(root),
        "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
        "publishers": {"default": {"type": "file"}, "platforms": {"kuaishou": {"type": "file", "account": "acct"}}},
        "notifications": {"log_path": str(root / "notifications.jsonl")},
    })


def test_explicit_content_lane_survives_account_binding():
    """MED34: the overnight brief lane tags the reference samples; the rulebook id stays the account lane."""
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {"lane": "real_world_ai_implementation"})
    assert job["brief"]["lane"] == "real_world_ai_implementation"
    assert job["brief"]["account_lane"] == "real_world_ai_implementation_v1"


def test_rulebook_lane_is_the_default_without_a_brief_lane():
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {})
    assert job["brief"]["lane"] == "real_world_ai_implementation_v1"


def test_a_different_brief_lane_is_still_replaced_by_the_rulebook_lane():
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {"lane": "pet_healing"})
    assert job["brief"]["lane"] == "real_world_ai_implementation_v1"


def test_overnight_kuaishou_beats_are_frozen_for_the_receipt_and_get_a_voice_plan():
    """MED38: Kuaishou had no frozen narration, so asset semantics were never bound and every beat failed."""
    from unittest.mock import patch

    from content_platform.media import MediaBridge
    from content_platform.pipeline import Pipeline

    body = "。".join(f"第{i}步把客服工单按紧急程度分类再交给对应同事处理" for i in range(1, 9)) + "。"
    overnight = {"lane": "real_world_ai_implementation", "platform_source_matrix": {"x": 1}, "hot_viral_samples": [{}]}
    plan = {"required": True, "visual_contract": [{"beat_id": "s01"}]}
    draft = {"title": "t", "body": body, "draft_meta": {"video_toolchain_plan": plan}}
    assert Pipeline._freeze_overnight_video_beats("kuaishou", overnight, draft) is True
    assert draft["draft_meta"]["video_script"] == MediaBridge.compile_video_script({"body": body, "draft_meta": {}})["script"]
    # Native lanes (no overnight samples), the pet lane and non-video drafts are left alone.
    for platform, brief, meta in (("kuaishou", {"lane": "x"}, {"video_toolchain_plan": plan}),
                                  ("douyin_pet", overnight, {"video_toolchain_plan": plan}),
                                  ("juejin", overnight, {"video_toolchain_plan": {"required": False}})):
        other = {"body": body, "draft_meta": dict(meta)}
        assert Pipeline._freeze_overnight_video_beats(platform, brief, other) is False
        assert "video_script" not in other["draft_meta"]
    seen = {}

    def bind(store, job_id, brief, script, scenes, platform, owner):
        seen["script"] = script
        return [{"intent": {key: "x" for key in ("beat_id", "claim", "asset_role", "semantic_subject",
                                                   "content_match_reason")}}]

    with tempfile.TemporaryDirectory() as tmp, \
            patch("content_platform.video_asset_semantics.bind_requirements", side_effect=bind), \
            patch("content_platform.video_asset_semantics.requirement_tag", return_value="asset-requirement:x"):
        pipeline = _pipeline(Path(tmp))
        prompts = []

        def call(prompt, brief):
            prompts.append(prompt)
            return json.dumps({"voice_plan": [{"index": i, "style": "平稳", "semantic_direction": "说明步骤", "rate": "+0%",
                                               "pitch": "+0Hz", "pause_after_ms": 300} for i in range(8)]})

        with patch.object(pipeline.generator, "_call_hermes_text", side_effect=call):
            pipeline._bind_video_asset_semantics("j", draft, {"kuaishou": overnight}, "o")
        source = draft["draft_meta"]["voice_plan_source"]
        assert Path(source["path"]).is_file() and draft["draft_meta"]["voice_plan_audit"]["accepted"] is True
    assert seen["script"] == draft["draft_meta"]["video_script"]
    assert "kuaishou AI 实操短视频" in prompts[0] and "抖音宠物" not in prompts[0]
    assert draft["draft_meta"]["video_toolchain_plan"]["visual_contract"][0]["required_semantic_tag"] == "asset-requirement:x"


def test_bind_requirements_uses_the_receipt_for_overnight_lanes_and_bound_planning_for_native_ones():
    from unittest.mock import MagicMock, patch

    from content_platform.video_asset_semantics import bind_requirements

    store = MagicMock()
    store.events.return_value = []
    with patch("content_platform.video_planning_producer.read_bound_video_planning",
               side_effect=ValueError("bound_video_planning_required")) as bound:
        for brief, expected in (({"platform_source_matrix": {"x": 1}, "hot_viral_samples": [{}]}, "semantic_factual_safety_receipt_required"),
                                ({}, "bound_video_planning_required")):
            try:
                bind_requirements(store, "j", brief, "script", [], "kuaishou", "o")
            except ValueError as exc:
                assert str(exc) == expected
            else:
                raise AssertionError("expected a refusal")
    assert bound.call_count == 1
