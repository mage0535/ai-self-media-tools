#!/usr/bin/env python3
"""短视频脚本质量门禁（2026-08-14 基于中英文爆款方法论创建）

综合来源：
- 抖音爆款策划师（yaojingang）：完播率优化 4 条（开头3秒抛场景悬念/每10秒新信息点/结尾前置/口播≤60秒）
- douyin-script（5tldr/claude-skills）：黄金3秒 4 类型（悬念/利益/反常识/共鸣）+ 60秒结构（Hook→痛点→干货→总结→互动）
- tiktok-viral-hooks（shixinzhang）：7 种观众心理钩子 + 第7/14/21秒 retention moves
- 杜杜老师抖音笔记：7 心理钩子 + 流量口诀（开头定生死/悬念多完播高/争议多评论多/共鸣多点赞多/实用多收藏多）

检查维度：开头3秒钩子 / 信息点密度 / 结尾互动 / 口语化（短句+无AI套话）/ 每段长度 / 情绪词 / 争议或共鸣点
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# AI 套话/机器感词（命中即扣分）
AI_CLICHES = [
    "首先", "其次", "最后", "总之", "综上所述", "值得注意的是",
    "不仅如此", "总而言之", "简单来说", "需要注意的是", "让我们来",
    "接下来", "除此之外", "换句话说", "这意味着", "事实上",
    "not only", "furthermore", "moreover", "additionally", "in conclusion",
]
# 钩子类型关键词（开头 3 秒应命中至少 1 类）
HOOK_PATTERNS = {
    "悬念": [r"为什么", r"怎么办", r"如何", r"竟然", r"居然", r"没想到", r"秘密", r"真相", r"后悔没", r"不会告诉你", r"结果它", r"结果居然", r"[?？]"],
    "利益": [r"赚", r"省", r"免费", r"学会", r"月入", r"涨", r"提升", r"技巧", r"攻略", r"\d+分钟学会", r"\d+秒"],
    "反常识": [r"别", r"千万别", r"都错了", r"一直", r"原来", r"错了", r"误区", r"别再做", r"浪费时间", r"反而", r"更差", r"根本", r"第一步就", r"\d+%的人", r"90%", r"别再", r"stop\b", r"wrong", r"mistake", r"worse", r"don't use", r"overrated", r"waste of time"],
    "共鸣": [r"有没有人", r"是不是", r"你也", r"都一样", r"打工", r"打工人", r"头疼", r"崩溃", r"烦", r"想放弃", r"坚持不下去", r"emo"],
}
# 情绪词（真实感信号）
EMOTION_WORDS = ["气死", "离谱", "太爽", "崩溃", "后悔", "惊喜", "意外", "心疼", "绝了", "真香", "emo", "难受", "炸裂", "跪了", "离谱", "离谱"]
# 互动引导（结尾应有）
CTA_PATTERNS = [r"关注", r"点赞", r"收藏", r"评论", r"扣\d", r"回复", r"评论区", r"转发", r"关注我", r"下期", r"follow", r"like", r"comment", r"share", r"tell me", r"try it"]


def check_hook(text: str) -> dict:
    head = text[:120]
    hits = {}
    for name, pats in HOOK_PATTERNS.items():
        matched = [p for p in pats if re.search(p, head, re.IGNORECASE)]
        if matched:
            hits[name] = matched
    return {"passed": len(hits) >= 1, "hook_types": list(hits.keys()), "matched": hits}


def check_ai_cliches(text: str) -> dict:
    found = [c for c in AI_CLICHES if c in text]
    return {"passed": len(found) == 0, "found": found}


def check_cta(text: str) -> dict:
    found = [p for p in CTA_PATTERNS if re.search(p, text[-200:])]
    return {"passed": len(found) >= 1, "found": found}


def check_emotion(text: str) -> dict:
    found = [w for w in EMOTION_WORDS if w in text]
    return {"passed": len(found) >= 1, "found": found}


def check_segments(segments: list[str], lang: str) -> dict:
    issues = []
    for i, seg in enumerate(segments, 1):
        length = len(seg)
        if lang == "zh":
            if length > 80:
                issues.append(f"段{i} 过长({length}字>80)")
        else:
            if length > 100:
                issues.append(f"seg{i} too long({length}chars>100)")
    return {"passed": len(issues) == 0, "issues": issues}


def check_info_density(segments: list[str], min_points: int = 3) -> dict:
    """每 10 秒应有新信息点 → 8 段至少 3 段含具体数字/工具名/结果"""
    dense = 0
    for seg in segments:
        has_num = bool(re.search(r"\d+", seg))
        has_tool = bool(re.search(r"[A-Z][a-zA-Z]{2,}", seg)) or bool(re.search(r"[\u4e00-\u9fff]{2,}", seg))
        has_result = bool(re.search(r"成功|失败|涨|降|提升|结果|测试|实测|win|lose|result|test", seg, re.I))
        if has_num and (has_tool or has_result):
            dense += 1
    return {"passed": dense >= min_points, "dense_segments": dense, "required": min_points}


def validate_script(script_text: str, lang: str = "zh") -> dict:
    segments = [s.strip() for s in re.split(r"\n\s*\n", script_text) if s.strip()]
    checks = {
        "hook_3s": check_hook(script_text),
        "ai_cliches": check_ai_cliches(script_text),
        "cta": check_cta(script_text),
        "emotion": check_emotion(script_text),
        "segments": check_segments(segments, lang),
        "info_density": check_info_density(segments),
    }
    failed = [k for k, v in checks.items() if not v["passed"]]
    return {
        "passed": not failed,
        "segment_count": len(segments),
        "checks": checks,
        "failed": failed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="短视频脚本质量门禁")
    ap.add_argument("script", help="脚本文件路径")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    text = Path(args.script).read_text(encoding="utf-8")
    result = validate_script(text, args.lang)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"脚本质量: {'✅ PASS' if result['passed'] else '❌ FAIL'}")
        print(f"  段数: {result['segment_count']}")
        for k, v in result["checks"].items():
            status = "✅" if v["passed"] else "❌"
            detail = json.dumps(v, ensure_ascii=False)[:80]
            print(f"  {status} {k}: {detail}")
        if result["failed"]:
            print(f"  失败项: {result['failed']}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
