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


def test_kuaishou_video_beats_are_frozen_and_bound_like_the_pet_narration():
    """MED38: Kuaishou had no frozen narration, so asset semantics were never bound and every beat failed."""
    from unittest.mock import patch

    from content_platform.media import MediaBridge

    body = "。".join(f"第{i}步把客服工单按紧急程度分类再交给对应同事处理" for i in range(1, 9)) + "。"
    draft = {"title": "t", "body": body, "draft_meta": {"video_toolchain_plan": {"required": True, "visual_contract": [{"beat_id": "s01"}]}}}
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
            n = len(prompt.split("\n\n")) and 8
            return json.dumps({"voice_plan": [{"index": i, "style": "平稳", "semantic_direction": "说明步骤", "rate": "+0%",
                                               "pitch": "+0Hz", "pause_after_ms": 300} for i in range(n)]})

        with patch.object(pipeline.generator, "_call_hermes_text", side_effect=call):
            pipeline._bind_video_asset_semantics("j", draft, {"kuaishou": {"lane": "real_world_ai_implementation"}}, "o")
        source = draft["draft_meta"]["voice_plan_source"]
        assert Path(source["path"]).is_file() and draft["draft_meta"]["voice_plan_audit"]["accepted"] is True
    assert "kuaishou AI 实操短视频" in prompts[0] and "抖音宠物" not in prompts[0]
    assert seen["script"] == MediaBridge.compile_video_script({"body": body, "draft_meta": {}})["script"]
    assert draft["draft_meta"]["video_script"] == seen["script"]
    assert draft["draft_meta"]["video_toolchain_plan"]["visual_contract"][0]["required_semantic_tag"] == "asset-requirement:x"
