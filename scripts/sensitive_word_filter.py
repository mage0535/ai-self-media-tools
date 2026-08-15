#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sensitive_word_filter.py — 敏感词过滤门禁（2026-08-14 用户复盘要求落地）

覆盖范围：视频 TTS 文案 / 字幕 / 封面文字三重过滤，以及图文正文。
用法：
    from sensitive_word_filter import check_content
    result = check_content("文案文本")
    result = {"ok": True/False, "hits": [...], "text": 清洗后文本}

CLI:
    python3 sensitive_word_filter.py <file_or_text> [--json]
"""
import re
import sys
import json
import os

# ---------- 基础词库（可扩充；CUSTOM_WORDS 支持追加） ----------
BASE_WORDS = [
    # 政治/政权红线（抖音重点）
    "政治敏感", "反党", "颠覆国家", "台独", "港独", "疆独", "藏独", "法轮功", "六四", "天安门事件",
    "领导人负面", "习近平负面", "中央负面", "政府负面",
    # 涉政敏感词
    "军火", "枪支", "爆炸物制造",
    # 违法/犯罪
    "赌博网站", "博彩", "外围女", "裸聊", "代孕", "贩卖毒品", "制毒", "吸毒教程", "洗钱",
    # 色情
    "色情", "情色", "嫖娼", "援交", "裸贷", "幼女", "性交易",
    # 暴力恐怖
    "杀人教程", "自杀教程", "恐怖袭击", "人体炸弹",
    # 欺诈/传销
    "传销", "庞氏骗局", "电信诈骗", "刷单诈骗", "资金盘",
    # 医疗/金融绝对化用语（广告法）
    "根治", "包治百病", "药到病除", "百分百治愈", "永不复发", "稳赚不赔", "保本保息", "100%收益",
    # 极限词（广告法禁用）
    "最顶级", "最高级", "最佳", "全网第一", "全球第一", "国家级", "世界级", "顶级产品",
    # 未成年人/隐私
    "未成年色情", "人肉搜索", "开盒",
    # 平台违规
    "刷粉", "刷赞", "买粉", "刷流量", "外挂", "破解版", "私服",
]

# 自定义词库（平台运行中累积，不得删除）
CUSTOM_WORDS = [
    # 抖音/快手曾屏蔽过的词（2026-08-12 复盘回溯补充）
    "抖音官方", "官方运营", "流量加持",  # 注意：这里只拦截夸大官方背书表述，官方活动邀请本身不拦截
]

# 合并词库并排序（长词优先，避免短词误伤长词）
ALL_WORDS = sorted(set(BASE_WORDS + CUSTOM_WORDS), key=len, reverse=True)

# 构建正则（分词边界宽松匹配，中文直接包含即可）
_PATTERNS = [re.compile(re.escape(w)) for w in ALL_WORDS]


def check_content(text: str, context: str = "general", extra_words: list | None = None):
    """
    检查文本中的敏感词。
    :param text: 要检查的文本（TTS/字幕/封面文字/正文）
    :param context: 用途标签（tts / subtitle / cover / body）
    :param extra_words: 追加自定义词（单次调用）
    :return: {"ok": bool, "hits": [{"word","context"}], "text": 清洗后文本, "total": N}
    """
    if not text:
        return {"ok": True, "hits": [], "text": text, "total": 0}
    words = ALL_WORDS
    if extra_words:
        words = sorted(set(words + list(extra_words)), key=len, reverse=True)
    hits = []
    cleaned = text
    for w in words:
        if w in cleaned:
            hits.append({"word": w, "context": context})
            # 清洗：保留首尾字，中间打码
            if len(w) <= 2:
                cleaned = cleaned.replace(w, "*" * len(w))
            else:
                cleaned = cleaned.replace(w, w[0] + "*" * (len(w) - 2) + w[-1])
    return {"ok": len(hits) == 0, "hits": hits, "text": cleaned, "total": len(hits)}


def check_file(path: str, context: str = "file"):
    """检查文件中的全部文本（按行）。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    res = check_content(content, context=context)
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_json = "--json" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(0)
    target = args[0]
    if os.path.isfile(target):
        result = check_file(target)
    else:
        result = check_content(target)
    if use_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"[PASS] 无敏感词 ({result['total']} hits)")
        else:
            print(f"[FAIL] 发现 {result['total']} 个敏感词:")
            for h in result["hits"]:
                print(f"  - {h['word']} ({h['context']})")
            print(f"[清洗后] {result['text']}")
    sys.exit(0 if result["ok"] else 1)
