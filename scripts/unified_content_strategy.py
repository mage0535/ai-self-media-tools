#!/usr/bin/env python3
"""
统一内容策略引擎 — 全渠道趋势分析→选题→内容生成→发布
核心原则：内容给真人看的，不是给机器/AI看的
"""
import json, os, random, re, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "content_platform"))
from humanize import naturalize_copy, quality_gate

HOME = Path.home() / ".ai-self-media-tools"
DATA = HOME / "data"
CONFIG = HOME / "config"
RULEBOOK = json.loads((CONFIG / "channel_content_rulebook.json").read_text())

# ── 人类化质量门禁 ────────────────────────────
HUMAN_CHECKLIST = {
    "opening_hook": "开头必须有钩子（具体数字/反问/个人经历/反常识）",
    "no_template_openings": "禁止'在当今时代''随着科技的发展''众所周知'等开头",
    "has_specifics": "必须有具体细节（数字/工具名/人名/场景），不能泛泛而谈",
    "real_voice": "用'我'/'我们'第一人称，有个人观点和立场",
    "no_ai_transitions": "禁止'首先/其次/最后''值得注意的是''综上所述'等AI常用过渡词",
    "conversational": "口语化，像在跟朋友聊天，不是写论文",
    "emotion_or_hook": "有情绪（兴奋/吐槽/惊讶）或强钩子，不能平铺直叙",
    "relevant_images": "配图必须与正文内容相关：技术文章用界面截图/代码截图/架构图，禁止随机占位图",
}


def human_quality_check(text, title=""):
    """检查内容是否像真人写的，返回问题列表。"""
    issues = []

    # 检查模板开头
    bad_openings = ["在当今|随着科技|众所周知|近年来|在数字化|在人工智能|随着互联网"]
    for pat in bad_openings:
        if re.search(pat, text[:100]):
            issues.append(f"开头模板化: '{pat}'")

    # 检查AI过渡词
    ai_words = ["首先", "其次", "最后", "综上所述", "值得注意的是", "不可忽视的是", "毋庸置疑", "换言之", "由此可见", "显而易见"]
    for w in ai_words:
        if w in text:
            issues.append(f"AI过渡词: '{w}'")

    # 检查是否有具体细节
    has_numbers = bool(re.search(r'\d+', text))
    if not has_numbers:
        issues.append("缺少具体数字/数据")

    # 检查是否有人称
    if not re.search(r'[我我们]', text):
        issues.append("缺少第一人称视角")

    # 检查钩子
    hooks = ["?", "！", "？", "!", "震惊", "没想到", "居然", "后悔", "推荐", "免费", "简单", "快"]
    has_hook = any(h in text[:200] for h in hooks)
    if not has_hook:
        issues.append("前200字缺少钩子（问号/感叹词/情绪词）")

    return issues


def generate_hook(topic, platform):
    """根据话题和平台生成自然钩子。"""
    hooks_pool = {
        "通用": [
            f"试了{random.choice(['10+','5个','几十个'])}工具后，{random.choice(['我只推荐这一个','我后悔没早用','这个太香了','这个真没想到'])}",
            f"做了{random.choice(['3年','半年','2年'])}{random.choice(['开发','运营','自动化'])},{random.choice(['说点大实话','分享点干货','总结几条经验'])}",
        ],
        "对比": [
            f"{random.choice(['同样是AI工具','同样是自动化方案','同样是写代码'])},{random.choice(['差距咋这么大','区别太大了','选对效率翻倍'])}",
        ],
        "教程": [
            f"{random.choice(['别再说不会了','别再手动做了','别再浪费时间了'])}, {random.choice(['3步搞定','5分钟学会','一行代码解决'])}",
        ],
    }

    # 选匹配的模板
    for key, pool in hooks_pool.items():
        if key == "通用" or key in topic:
            return random.choice(pool)

    return random.choice(hooks_pool["通用"])


def select_topics_by_trend(channels, count=5):
    """基于趋势分析选题（当前为规则轮询，可对接趋势API）。"""
    # 简版：轮询话题池+考虑日期
    topics_pool = [
        {"title": "5个让你效率翻倍的免费AI工具", "lane": "ai_efficiency", "hook": "试了20多个AI工具，最后只留下这5个"},
        {"title": "用Python自动化办公，每天省下2小时", "lane": "ai_efficiency", "hook": "以前手动搞一下午，现在点一下就行"},
        {"title": "搭建个人AI知识库的3种方法", "lane": "ai_efficiency", "hook": "别再收藏了，真正有用的就这3个"},
        {"title": "GitHub Copilot vs Codeium，谁更好用", "lane": "ai_efficiency", "hook": "花了2周深度对比，结果很意外"},
        {"title": "开源项目推荐：这个AI工具惊艳到我了", "lane": "open_source", "hook": "刷GitHub时发现的项目，太强了"},
        {"title": "n8n搭建自动化工作流入门", "lane": "ai_efficiency", "hook": "不会代码也能搭自动化，太简单了"},
        {"title": "AI写作助手横评：谁最懂中文", "lane": "ai_efficiency", "hook": "测了5个AI写作工具，结果就一个能打"},
    ]

    selected = random.sample(topics_pool, min(count, len(topics_pool)))
    return selected


def compose_for_platform(topic_info, platform):
    """根据平台类型生成适配内容。"""
    title = topic_info["title"]
    hook = topic_info.get("hook", "")

    # 正文生成（简版）
    body_templates = {
        "short": f"{hook}。\n\n最近一直在用这个工具，确实好用。推荐给大家。\n\n#AI效率 #工具推荐",
        "article": f"{hook}。\n\n## 为什么推荐\n\n用了之后确实效率提升很多。\n\n## 具体功能\n\n- 功能一：简单易用\n- 功能二：免费开源\n- 功能三：持续更新\n\n## 总结\n\n如果你也在找效率工具，可以试试这个。",
        "video_script": f"{hook}。\n\n今天给大家分享一个超好用的工具。\n\n第一步：下载安装\n第二步：配置使用\n第三步：感受效率提升\n\n记得关注，下期更精彩。",
    }

    if platform in ("twitter", "bluesky", "nostr"):
        content = body_templates["short"][:280]
        return {"title": "", "body": content, "kind": "short"}
    elif platform in ("zhihu", "juejin", "wechat", "devto"):
        content = body_templates["article"]
        return {"title": title[:64], "body": content, "kind": "article"}
    elif platform in ("youtube", "tiktok", "douyin", "kuaishou"):
        return {"title": title[:30], "body": body_templates["video_script"], "kind": "video"}
    else:
        return {"title": title[:64], "body": body_templates["article"], "kind": "article"}


def run_strategy(channels=None, dry_run=True):
    """执行完整策略→内容→发布流程。"""
    print(f"\n{'='*60}")
    print(f"📊 统一内容策略引擎 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # Step 1: 趋势分析 + 选题
    print("\n🔍 [Step 1] 趋势分析与选题")
    topics = select_topics_by_trend(channels, count=5)
    for i, t in enumerate(topics, 1):
        hook_issue = human_quality_check(t["hook"], t["title"])
        hook_status = "✅" if not hook_issue else f"⚠️ {hook_issue[0]}"
        print(f"  {i}. {t['title']}")
        print(f"     钩子: {t['hook']} {hook_status}")

    # Step 2: 内容生成 + 人类化质检
    print("\n✍️ [Step 2] 内容生成与人类化质检")
    for t in topics:
        issues = human_quality_check(t["hook"] + t["title"])
        if issues:
            print(f"  ⚠️ '{t['title'][:30]}...' → {'; '.join(issues[:2])}")
            # 自动修复：重新生成钩子
            t["hook"] = generate_hook(t["title"], "通用")
            print(f"     ✅ 已重写钩子: {t['hook']}")

    # Step 3: 平台适配
    if channels:
        print(f"\n🔄 [Step 3] 平台适配分发")
        for ch in channels:
            t = topics[len(topics) % len(topics)]
            content = compose_for_platform(t, ch)
            print(f"  → {ch:15s} | kind={content['kind']:10s} | title={content['title'][:30]}")

    print(f"\n{'='*60}")
    print(f"✅ 策略完成 | {len(topics)} 个选题")
    print(f"{'='*60}")

    return topics


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="+", help="目标平台列表")
    parser.add_argument("--no-dry-run", action="store_true", help="实际执行")
    args = parser.parse_args()

    run_strategy(args.channels, dry_run=not args.no_dry_run)
