"""Deterministic four-axis content profile used before model generation."""

from __future__ import annotations

import re


DOMAIN = {
    "tech": ["编程", "代码", "api", "ai", "工具", "效率", "工作流", "自动化", "教程", "部署"],
    "pets": ["猫", "狗", "宠物", "萌宠", "猫咪", "狗狗"],
    "finance": ["股票", "基金", "投资", "理财", "财报", "利率"],
    "culture": ["文化", "非遗", "博物馆", "书法", "古城", "民俗", "文物"],
    "science": ["科学", "物理", "宇宙", "量子", "基因", "实验"],
}
TREATMENT = {
    "cinematic": ["电影感", "cinematic", "运镜", "镜头语言", "电影级", "构图"],
    "documentary": ["纪实", "纪录片", "现场", "实拍"],
    "zine": ["zine", "纸刊", "手撕纸", "编辑海报"],
    "editorial": ["海报", "排版", "视觉体系"],
}
TONE = {
    "urgent": ["紧急", "马上", "立刻", "倒计时", "别再"],
    "playful": ["有趣", "搞笑", "离谱", "可爱", "萌"],
    "warm": ["温暖", "治愈", "陪伴", "暖心"],
    "authoritative": ["实测", "证据", "专业", "分析", "真相"],
}


def _hit(text: str, term: str) -> bool:
    if term.isascii() and term.isalpha():
        return bool(re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text.casefold()))
    return term.casefold() in text.casefold()


def _best(text: str, mapping: dict[str, list[str]], default: str) -> tuple[str, dict[str, int]]:
    scores = {key: sum(1 for term in terms if _hit(text, term)) for key, terms in mapping.items()}
    scores = {key: score for key, score in scores.items() if score}
    return (max(scores, key=scores.get), scores) if scores else (default, {})


def classify_content_profile(text: str, platform: str = "", content_format: str = "") -> dict:
    text = str(text or "")
    domain, domain_scores = _best(text, DOMAIN, "general")
    treatment, treatment_scores = _best(text, TREATMENT, "editorial")
    tone, tone_scores = _best(text, TONE, "authoritative")
    fmt = content_format or {
        "xiaohongshu": "carousel", "wechat": "article", "zhihu": "article", "juejin": "article",
        "bilibili": "long_video", "youtube": "long_video",
    }.get(str(platform).casefold(), "short_video")
    return {
        "content_domain": domain,
        "content_format": fmt,
        "visual_treatment": treatment,
        "emotional_tone": tone,
        "platform": str(platform),
        "evidence": {"domain": domain_scores, "treatment": treatment_scores, "tone": tone_scores},
    }


def detect_genre_safe(text: str, lang: str = "auto") -> str:
    return classify_content_profile(text).get("content_domain", "general")
