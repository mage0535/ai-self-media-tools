import json
import types
from pathlib import Path

from content_platform.voice_plan import build_voice_plan

from content_platform.pipeline import Pipeline

GOOD = """你是不是也以为养两只高智商猫是双倍快乐，现实往往是翻车现场？
第1步，门窗和柜门升级双重物理童锁，选旋转或暗扣卡扣。
第2步，零食和主粮全部收进咬不穿的金属铁盒并密封好。
分区分开喂食，切断2只猫相互掩护盗食的可能。
第3步，每天提供3套难度递增的漏食玩具消耗精力。
若疑似吞食异物，必须立即送医由兽医确诊排查。
这份物理隔绝加精力疏导的避坑清单，太离谱的拆家都能防。
建议收藏，你家猫咪最离谱的开锁操作是什么，评论区说说？"""


VOICE = json.dumps({"voice_plan": [{"index": i, "style": "轻松", "semantic_direction": "讲做法", "rate": "+0%",
                                    "pitch": "+0Hz", "pause_after_ms": 300} for i in range(8)]}, ensure_ascii=False)


def _run(replies, tmp_path=None):
    calls = []

    def call(prompt, brief):
        calls.append(prompt)
        return replies.pop(0)

    events = []
    fake = types.SimpleNamespace(generator=types.SimpleNamespace(_call_hermes_text=call),
                                 store=types.SimpleNamespace(record_event=lambda *a: events.append(a),
                                                             path=(tmp_path or Path("/nonexistent")) / "state.db"),
                                 PET_NARRATION_PROMPT=Pipeline.PET_NARRATION_PROMPT,
                                 PET_VOICE_PLAN_PROMPT=Pipeline.PET_VOICE_PLAN_PROMPT)
    fake._write_pet_voice_plan = lambda *a: Pipeline._write_pet_voice_plan(fake, *a)
    draft = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    Pipeline._write_pet_narration(fake, "j1", draft, {"douyin_pet": {}})
    assert events and events[0][1] == "pet_narration_written"
    return draft["draft_meta"], calls


def test_model_narration_that_passes_the_script_gate_is_frozen(tmp_path):
    meta, calls = _run([GOOD, "```json\n" + VOICE + "\n```"], tmp_path)
    assert len(calls) == 2 and meta["pet_narration_audit"]["accepted"] is True
    assert meta["video_script"].count("\n\n") == 7
    # The renderer's normal_film_audio.source_plan reads exactly this pinned file.
    source = meta["voice_plan_source"]
    beats = meta["video_script"].split("\n\n")
    plan = json.loads(Path(source["path"]).read_text(encoding="utf8"))["voice_plan"]
    assert [row["text"] for row in build_voice_plan(beats, segment_styles=plan)] == beats
    assert meta["pet_narration_audit"]["voice_plan"]["sha256"] == source["sha256"]


def test_invalid_voice_plan_is_retried_then_left_missing(tmp_path):
    bad = VOICE.replace('"+0%"', '"fast"')
    meta, calls = _run([GOOD, bad, "不是JSON"], tmp_path)
    assert len(calls) == 3 and "voice_plan_source" not in meta
    audit = meta["pet_narration_audit"]["voice_plan"]
    assert audit["accepted"] is False and audit["attempts"][0]["failed"][0].startswith("voice_plan_rate_invalid")


def test_narration_failing_the_gate_twice_leaves_the_old_path():
    meta, calls = _run(["一只猫\n两只猫", "只有一行文字但是没有任何结尾", "还是只有一行"])
    assert len(calls) == 3 and meta["pet_narration_audit"]["accepted"] is False
    assert "上一版有2段" in calls[1]
    assert "video_script" not in meta


def test_two_sentence_beat_that_the_compiler_would_split_is_rejected():
    split = GOOD.replace("你是不是也以为养两只高智商猫是双倍快乐，现实往往是翻车现场？",
                         "你是不是也以为养两只高智商猫是双倍快乐？现实往往是翻车现场！")
    meta, calls = _run([split, split, split])
    assert meta["pet_narration_audit"]["accepted"] is False
    assert meta["pet_narration_audit"]["attempts"][0]["failed"] == ["beat_resplit"]


def test_prompt_asks_for_one_scene_per_beat():
    # r100: beat s04 listed three actions plus an invisible goal; its image scored 0.52.
    assert "一段只写一个画面" in Pipeline.PET_NARRATION_PROMPT


def test_rejected_beat_carries_the_reviewer_reason(tmp_path):
    import pytest
    from content_platform.video_asset_semantics import admit_review, build_requirements
    scenes = [{"beat_id": f"s0{i + 1}", "visual_mode": "photo", "template_id": "t", "group_motion": "m"} for i in range(8)]
    requirement = build_requirements("\n".join(f"第{i}段" for i in range(8)), scenes)[3]
    image = tmp_path / "s04.png"
    image.write_bytes(b"x")
    review = {"status": "evaluated", "requirement_match": False, "score": 0.52, "image_observed": True,
              "reason": "shows one cat at a bowl;\n no second room or closed door"}
    with pytest.raises(ValueError, match=r"beat=s04:score=0.52:match=False:observed=True:why=shows one cat at a bowl; no second room"):
        admit_review(image, "topic", requirement, review)
