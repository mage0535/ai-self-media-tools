import types

from content_platform.pipeline import Pipeline

GOOD = """你是不是也以为养两只高智商猫是双倍快乐？现实往往是翻车现场。
第1步，门窗和柜门升级双重物理童锁，选旋转或暗扣卡扣。
第2步，零食和主粮全部收进咬不穿的金属铁盒并密封好。
分区分开喂食，切断2只猫相互掩护盗食的可能。
第3步，每天提供3套难度递增的漏食玩具消耗精力。
若疑似吞食异物，必须立即送医由兽医确诊排查。
这份物理隔绝加精力疏导的避坑清单，太离谱的拆家都能防。
建议收藏！你家猫咪最离谱的开锁操作是什么？评论区说说。"""


def _run(replies):
    calls = []

    def call(prompt, brief):
        calls.append(prompt)
        return replies.pop(0)

    events = []
    fake = types.SimpleNamespace(generator=types.SimpleNamespace(_call_hermes_text=call),
                                 store=types.SimpleNamespace(record_event=lambda *a: events.append(a)),
                                 PET_NARRATION_PROMPT=Pipeline.PET_NARRATION_PROMPT)
    draft = {"body": "草稿正文", "draft_meta": {"video_toolchain_plan": {"required": True}}}
    Pipeline._write_pet_narration(fake, "j1", draft, {"douyin_pet": {}})
    assert events and events[0][1] == "pet_narration_written"
    return draft["draft_meta"], calls


def test_model_narration_that_passes_the_script_gate_is_frozen():
    meta, calls = _run([GOOD])
    assert len(calls) == 1 and meta["pet_narration_audit"]["accepted"] is True
    assert meta["video_script"].count("\n\n") == 7


def test_narration_failing_the_gate_twice_leaves_the_old_path():
    meta, calls = _run(["一只猫\n两只猫", "只有一行文字但是没有任何结尾"])
    assert len(calls) == 2 and meta["pet_narration_audit"]["accepted"] is False
    assert "video_script" not in meta
