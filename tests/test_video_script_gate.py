#!/usr/bin/env python3
"""video_script_gate 钩子识别单测（2026-08-15 新增预期违背钩子支持后建立）

覆盖：
- 新增预期违背/反差钩子句式（T15-T17/H10-H11/E4 对应开头）
- 原有钩子回归（悬念/利益/共鸣不误判）
- 英文大小写（IGNORECASE）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from video_script_gate import check_hook

CASES = [
    # (文本, 期望通过, 说明)
    # --- 新增：预期违背/反差钩子 ---
    ("AI写周报是浪费时间", True, "T15 默认规则反转式"),
    ("养猫的人都知道，猫根本不治愈，除非它想", True, "T15 猫咪号内化"),
    ("90%的人喂猫粮第一步就错了", True, "T16 反常识数据式"),
    ("99%的人提示词写错了", True, "T16 变体"),
    ("做金融3年，我劝普通人别碰股票", True, "T17 预期违背揭秘式"),
    ("基金经理不会告诉你的3件事", True, "T17 悬念版"),
    ("打开AI写周报，结果它写了一篇小作文", True, "H10 预测打断式"),
    ("别再用AI写周报了", True, "H11 反常识断言开场"),
    ("你喂猫粮的顺序一直是错的", True, "H11 变体"),
    ("用了AI，你的效率反而变慢了", True, "反而句式"),
    # --- 英文 ---
    ("Stop using AI for this", True, "英文 Stop 大小写"),
    ("STOP USING AI FOR THIS", True, "英文全大写"),
    ("Your AI prompts are wrong", True, "英文 wrong"),
    ("AI writing reports is a waste of time", True, "英文 waste of time"),
    ("I replaced my tool and got worse results", True, "英文 worse"),
    # --- 回归：原有钩子 ---
    ("为什么你做的AI视频总像动画片？", True, "悬念提问式 T1"),
    ("3个技巧，让你的AI视频高级10倍", True, "数字干货式 T3"),
    ("这个AI技巧，90%的人不知道", True, "悬念稀缺式 T6"),
    ("做AI视频的第30天，我想放弃了...", True, "共鸣状态式 T8"),
]


def test_hook_cases():
    failed = []
    for text, expected, label in CASES:
        r = check_hook(text)
        if r["passed"] != expected:
            failed.append((label, text, r))
    assert not failed, f"{len(failed)} 条未通过: {failed}"
    print(f"check_hook: {len(CASES)}/{len(CASES)} 通过")


if __name__ == "__main__":
    test_hook_cases()
    print("ALL PASS")
