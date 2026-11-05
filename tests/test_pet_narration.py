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


def test_overnight_kuaishou_video_gets_its_own_narration_and_voice_plan(tmp_path):
    """MED40 (r108): the frozen first 8 body slices of an AI article failed the renderer's script gate (5 of 8 checks)."""
    calls, events = [], []
    replies = [GOOD, VOICE]

    def call(prompt, brief):
        calls.append(prompt)
        return replies.pop(0)

    fake = types.SimpleNamespace(generator=types.SimpleNamespace(_call_hermes_text=call),
                                 store=types.SimpleNamespace(record_event=lambda *a: events.append(a), path=tmp_path / "state.db"),
                                 PET_NARRATION_PROMPT=Pipeline.PET_NARRATION_PROMPT, VIDEO_NARRATION_PROMPT=Pipeline.VIDEO_NARRATION_PROMPT,
                                 PET_VOICE_PLAN_PROMPT=Pipeline.PET_VOICE_PLAN_PROMPT)
    fake._write_pet_voice_plan = lambda *a, **k: Pipeline._write_pet_voice_plan(fake, *a, **k)
    overnight = {"platform_source_matrix": {"x": 1}, "hot_viral_samples": [{}]}
    draft = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    Pipeline._write_pet_narration(fake, "j1", draft, {"kuaishou": overnight}, "kuaishou")
    meta = draft["draft_meta"]
    assert events[0][1] == "video_narration_written" and meta["video_narration_audit"]["accepted"] is True
    assert "kuaishou AI 实操短视频草稿" in calls[0] and "宠物" not in calls[0] and "kuaishou AI 实操短视频" in calls[1]
    assert meta["video_script"].count("\n\n") == 7 and "voice_plan_source" in meta
    native = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    Pipeline._write_pet_narration(fake, "j2", native, {"kuaishou": {}}, "kuaishou")
    assert "video_script" not in native["draft_meta"] and len(calls) == 2


def test_photo_first_narration_is_written_from_the_picked_photos(tmp_path):
    """MED42 (r110): stock photos matched 0-1 of 8 beats written first; beats are now written from 8 picked photos."""
    from unittest.mock import patch

    calls, events = [], []
    replies = [GOOD, VOICE]

    def call(prompt, brief):
        calls.append(prompt)
        return replies.pop(0)

    fake = types.SimpleNamespace(generator=types.SimpleNamespace(_call_hermes_text=call),
                                 store=types.SimpleNamespace(record_event=lambda *a: events.append(a), path=tmp_path / "state.db"),
                                 PET_NARRATION_PROMPT=Pipeline.PET_NARRATION_PROMPT, PET_VOICE_PLAN_PROMPT=Pipeline.PET_VOICE_PLAN_PROMPT,
                                 PHOTO_FIRST_PLATFORMS=Pipeline.PHOTO_FIRST_PLATFORMS)
    fake._write_pet_voice_plan = lambda *a, **k: Pipeline._write_pet_voice_plan(fake, *a, **k)
    photos = [{"path": f"p{i}.jpg", "sha256": str(i), "provider_result": {"provider": "pexels"}, "observed_subject": f"cat number {i}"}
              for i in range(8)]
    draft = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    with patch.object(Pipeline, "_select_beat_photos", return_value=photos):
        Pipeline._write_pet_narration(fake, "j1", draft, {"douyin_pet": {}})
    meta = draft["draft_meta"]
    assert "第N段配第N张照片" in calls[0] and "第8张照片：cat number 7" in calls[0] and calls[0].endswith("草稿：\n草稿正文")
    assert meta["beat_photo_plan"]["photos"] == photos and meta["pet_narration_audit"]["photo_first"] == 8


def test_beat_photos_are_unique_licensed_and_keep_to_the_pets(tmp_path):
    from unittest.mock import patch

    store = types.SimpleNamespace(path=tmp_path / "state.db")
    fake = types.SimpleNamespace(store=store, BEAT_PHOTO_QUERY_PROMPT=Pipeline.BEAT_PHOTO_QUERY_PROMPT,
                                 generator=types.SimpleNamespace(_call_hermes_text=lambda p, b: "\n".join(f"{i}. query {i}" for i in range(12))))
    content = iter([b"a", b"a", b"b", b"c", b"d", b"e", b"f", b"g", b"h", b"i", b"j", b"k"])
    observed = iter(["two cats", "a cat", "a woman at a desk", "kitten", "dog", "puppy", "cats", "dogs", "cat", "a dog"])

    def stock(prompt, output, size=""):
        Path(output).write_bytes(next(content))
        return {"provider": "pexels", "source_url": "https://www.pexels.com/photo/1/", "license": "Pexels"}

    with patch("content_platform.image_provider._stock_image", side_effect=stock), \
            patch("content_platform.asset_semantic_review.review_asset", side_effect=lambda *a, **k: {"observed_subject": next(observed)}):
        photos = Pipeline._select_beat_photos(fake, "j1", {"title": "t", "body": "b"}, {}, "douyin_pet")
    assert len(photos) == 8 and len({row["sha256"] for row in photos}) == 8
    assert "a woman at a desk" not in [row["observed_subject"] for row in photos]
    assert all(row["provider_result"]["source_url"].startswith("https://") for row in photos)


def _photo_first_run(tmp_path, replies, verdicts):
    from unittest.mock import patch

    calls, reviewed = [], []

    def call(prompt, brief):
        calls.append(prompt)
        return replies.pop(0)

    def review(path, title, beat, result, semantic_requirement=None):
        reviewed.append(beat)
        bad = verdicts(beat)
        return {"score": 0.4 if bad else 0.8, "requirement_match": not bad, "reason": "no person in the photo" if bad else ""}

    fake = types.SimpleNamespace(generator=types.SimpleNamespace(_call_hermes_text=call),
                                 store=types.SimpleNamespace(record_event=lambda *a: None, path=tmp_path / "state.db"),
                                 PET_NARRATION_PROMPT=Pipeline.PET_NARRATION_PROMPT, PET_VOICE_PLAN_PROMPT=Pipeline.PET_VOICE_PLAN_PROMPT,
                                 PHOTO_FIRST_PLATFORMS=Pipeline.PHOTO_FIRST_PLATFORMS)
    fake._write_pet_voice_plan = lambda *a, **k: {"accepted": False}
    photos = [{"path": f"p{i}.jpg", "sha256": str(i), "provider_result": {"provider": "pexels"}, "observed_subject": f"cat {i}"}
              for i in range(8)]
    draft = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    with patch.object(Pipeline, "_select_beat_photos", return_value=photos), \
            patch("content_platform.asset_semantic_review.review_asset", side_effect=review):
        Pipeline._write_pet_narration(fake, "j1", draft, {"douyin_pet": {}})
    return draft["draft_meta"], calls, reviewed


def test_beats_their_photos_do_not_show_are_rewritten_with_the_reviewer_reason(tmp_path):
    """MED43 (r112): beat s04 added a person intervening that its photo did not show (0.38)."""
    lines = GOOD.splitlines()
    fixed = "\n".join(lines[:3] + ["第3步，每天提供3套难度递增的漏食玩具，小猫正低头拨弄。"] + lines[4:])
    meta, calls, reviewed = _photo_first_run(tmp_path, [GOOD, fixed], lambda beat: beat == lines[3])
    assert meta["pet_narration_audit"]["accepted"] is True and meta["video_script"] == fixed.replace("\n", "\n\n")
    assert "第4段与第4张照片不符（no person in the photo）" in calls[1] and "上一版：" in calls[1]
    assert meta["pet_narration_audit"]["attempts"][0]["photo_mismatches"] == [4]
    assert len(reviewed) == 9  # unchanged beats are not reviewed again


def test_mismatches_left_after_the_retries_keep_the_best_script_for_the_media_gate(tmp_path):
    lines = GOOD.splitlines()
    worse = "\n".join(["那只猫" + line[3:] if i < 2 else line for i, line in enumerate(lines)])
    meta, calls, _ = _photo_first_run(tmp_path, [GOOD, worse, GOOD], lambda beat: beat == lines[3] or beat.startswith("那只猫"))
    assert len(calls) == 3 and meta["video_script"] == GOOD.replace("\n", "\n\n")
    assert meta["pet_narration_audit"]["photo_mismatches_left"] == 1 and "beat_photo_plan" in meta
