#!/usr/bin/env python3
"""platform_rules.py — 2026 平台运营规则加载器。

让 ai-self-media-tools 管线（不依赖 Hermes skill 目录）能识别并加载
2026 平台规则：data/platform_rules_2026.md（固化副本）。

用法:
  from content_platform.platform_rules import load_rules, rules_for_platform, platform_rules_brief

  rules = load_rules()                    # 全量规则 dict
  brief = rules_for_platform("douyin")    # 指定平台规则文本
  ctx = platform_rules_brief("douyin")    # 注入生成提示的浓缩文本
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_HOME = Path(__file__).resolve().parents[1]
RULES_FILE = PROJECT_HOME / "data" / "platform_rules_2026.md"
PUBLIC_RULES_FILE = PROJECT_HOME / "config" / "platform_rules_2026.md"
FALLBACK_SKILL = Path.home() / ".hermes" / "skills" / "content" / "platform-ops-rules-2026" / "SKILL.md"

_SECTION_MAP = {
    "douyin": ["抖音"],
    "xiaohongshu": ["小红书"],
    "xhs": ["小红书"],
    "rednote": ["小红书"],
    "wechat": ["公众号"],
    "gzh": ["公众号"],
    "wechat_official": ["公众号"],
    "weixin": ["公众号"],
    "shipinhao": ["视频号"],
    "kuaishou": ["快手"],
    "bilibili": ["B站"],
    "youtube": ["YouTube"],
    "tiktok": ["TikTok"],
    "zhihu": ["知乎"],
    "juejin": ["掘金"],
    "twitter": ["Twitter"],
    "x": ["Twitter"],
}

_CACHE: dict[str, str] | None = None


def load_rules() -> dict[str, str]:
    """加载规则文件，按 ## 分节返回 {section: text}。优先项目固化副本，回退 Hermes skill。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = RULES_FILE if RULES_FILE.is_file() else PUBLIC_RULES_FILE if PUBLIC_RULES_FILE.is_file() else FALLBACK_SKILL
    if not path.is_file():
        _CACHE = {}
        return _CACHE
    text = path.read_text(encoding="utf-8", errors="replace")
    # 跳过 YAML frontmatter（首个 --- 到第二个 ---）
    stripped = text.lstrip()
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    sections: dict[str, str] = {}
    current = "前言"
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if body:
                sections[current] = "\n".join(body).strip()
            current = line[3:].strip()
            body = []
        else:
            body.append(line)
    if body:
        sections[current] = "\n".join(body).strip()
    # 移除空「前言」
    if sections.get("前言") in (None, ""):
        sections.pop("前言", None)
    _CACHE = sections
    return sections


def rules_for_platform(platform: str) -> str:
    """返回指定平台对应的规则文本（跨别名命中所有相关分节）。"""
    platform = str(platform or "").casefold()
    if not platform:
        return ""
    sections = load_rules()
    targets = _SECTION_MAP.get(platform, [platform])
    matched = []
    for sec, body in sections.items():
        if any(t in sec for t in targets):
            matched.append(f"### {sec}\n{body}")
    if matched:
        return "\n\n".join(matched)
    # 兜底：已知平台（在 _SECTION_MAP 中但规则库无专节）返回核心规则；未知平台返回空
    known = platform in _SECTION_MAP or platform in {"douyin_ai", "douyin_pet"}
    if not known:
        return ""
    core = []
    for key in ("抖音（2026 算法重构", "小红书（星云 5.0", "公众号"):
        for sec, body in sections.items():
            if key in sec:
                core.append(f"### {sec}\n{body}")
    return "\n\n".join(core) if core else ""


def platform_rules_brief(platform: str, max_chars: int = 900) -> str:
    """生成适合注入内容生成提示的浓缩规则（限长）。"""
    full = rules_for_platform(platform)
    if not full:
        return ""
    # 提取高价值行（权重/必须/禁止/数字门槛/新规），压缩到 max_chars
    lines = []
    for line in full.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        if any(k in s for k in ("权重", "必须", "禁止", "禁", "⚠️", "TOP", "≥", "≤", "勾选", "声明",
                                "限流", "收藏率", "新规", "考核", "冷启动", "铁粉", "长尾", "留存",
                                "评论", "标签", "垂直", "时段", "红利", "公式", "开头", "标题")):
            lines.append(s)
    brief = "\n".join(lines)
    return brief[:max_chars]


def rules_available() -> bool:
    return bool(load_rules())


if __name__ == "__main__":
    print(f"rules_available: {rules_available()}")
    print(f"sections: {list(load_rules().keys())}")
    print("\n--- douyin brief ---")
    print(platform_rules_brief("douyin", 600))
    print("\n--- xiaohongshu brief ---")
    print(platform_rules_brief("xiaohongshu", 400))
