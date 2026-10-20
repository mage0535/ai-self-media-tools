#!/usr/bin/env python3
"""跨平台+跨日选题查重门禁 — 定题后、写analysis前必须跑
用法: python3 scripts/check_topic_ledger.py <platform> "<选题标题>"
退出码: 0=通过 1=撞题(禁止使用该选题)
"""
import json, sys, glob, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "data" / "topic_ledger"

def normalize_domain(text):
    """映射到主题域(与check_platform_topic_independence同逻辑的扩展版)"""
    t = str(text).casefold()
    domains = {
        "周报自动化": ["周报", "weekly report", "日报"],
        "skills治理": ["skills裁剪", "skills清理", "技能包管理", "无脑装"],
        "mcp实操": ["mcp接入", "mcp教程", "mcp配置"],
        "codex工作流": ["codex实战", "codex工作流", "codex流水线", "夜间流水线", "github actions"],
        "ai编程经验": ["反直觉经验", "使用心得", "90天", "重度使用"],
        "ai工具盘点": ["ai工具top", "效率工具排行", "少加班"],
    }
    for domain, kws in domains.items():
        if any(k in t for k in kws):
            return domain
    return ""

def main():
    if len(sys.argv) < 3:
        print("usage: check_topic_ledger.py <platform> <topic_title>")
        sys.exit(2)
    platform, topic = sys.argv[1], sys.argv[2]
    my_domain = normalize_domain(topic)
    conflicts = []

    # 扫全部历史台账
    for f in sorted(glob.glob(str(LEDGER_DIR / "*.json"))):
        ledger = json.load(open(f))
        date = ledger.get("date", "?")
        for item in ledger.get("used_topics", []):
            their_domain = normalize_domain(item.get("title","") + " " + item.get("topic_domain",""))
            same_platform = item["platform"] == platform
            # 规则1: 同平台7日内同域 → 拦
            # 规则2: 跨平台同域且非"独立分析的自然重叠" → 标记人工复核
            if my_domain and their_domain == my_domain:
                conflicts.append({"date": date, "platform": item["platform"],
                                  "same_platform": same_platform,
                                  "domain": my_domain, "title": item.get("title","")[:50]})

    # 域未识别时用字符相似度兜底(与check_platform_topic_independence同逻辑)
    if not my_domain and topic:
        def char_sim(a, b):
            sa = {ch for ch in a.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
            sb = {ch for ch in b.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
            if not sa or not sb: return 0.0
            return len(sa & sb) / min(len(sa), len(sb))
        for f in sorted(glob.glob(str(LEDGER_DIR / "*.json"))):
            ledger = json.load(open(f))
            date = ledger.get("date", "?")
            for item in ledger.get("used_topics", []):
                sim = char_sim(topic, item.get("title",""))
                if sim > 0.5:
                    conflicts.append({"date": date, "platform": item["platform"],
                                      "same_platform": item["platform"] == platform,
                                      "domain": f"char_sim_{sim:.2f}",
                                      "title": item.get("title","")[:50]})

    if conflicts:
        same_plat = [c for c in conflicts if c["same_platform"]]
        cross = [c for c in conflicts if not c["same_platform"]]
        print(f"❌ 撞题! 域={my_domain or '字符相似度兜底'}")
        for c in same_plat:
            print(f"  [阻断] 同平台 {c['date']} 已做: {c['title']}")
        for c in cross:
            print(f"  [警告] 跨平台 {c['platform']} {c['date']} 已做: {c['title']} — 需证明差异化角度")
        sys.exit(1)
    else:
        print(f"✅ 无撞题记录 (domain={my_domain or '未识别域'})")
        sys.exit(0)

if __name__ == "__main__":
    main()
