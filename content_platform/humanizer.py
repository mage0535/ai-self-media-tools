"""
humanizer.py — 基于 Humanizer-zh（12.6k⭐）的中文 AI 写作去痕桥接。

在 pipeline 草稿生成后，自动调用 Hermes LLM 应用 24 条 AI 写作检测规则
对文本进行人性化处理（去除 AI 痕迹），提升中文内容自然度。

集成方式：
    from .humanizer import humanize_text
    result = humanize_text(title, body)

Humanizer-zh 规则来源：
    - 翻译自 blader/humanizer
    - 参考 hardikpandya/stop-slop
    - 基于 Wikipedia:Signs of AI writing
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# Humanizer-zh 24 条规则的快速检测短语列表
# 用于预处理标记，辅助 LLM 做更精准的改写
AI_PATTERNS = {
    "overclaim_significance": [
        "作为", "标志着", "见证了", "是……的体现", "是……的证明",
        "极其重要", "至关重要", "核心的", "关键性的", "关键转折点",
        "凸显了", "彰显了", "不断演变的格局", "不可磨灭",
    ],
    "overclaim_media": [
        "独立报道", "知名专家", "活跃的社交媒体", "据报道",
        "行业报告显示", "观察者指出", "专家认为", "一些批评者认为",
    ],
    "ing_analysis": [
        "突出", "彰显", "确保", "反映", "象征", "培养", "促进", "展示",
    ],
    "promotional": [
        "拥有", "充满活力的", "丰富的", "坐落于", "位于",
        "令人叹为观止", "必游之地", "迷人的", "开创性的",
    ],
    "ai_vocabulary": [
        "此外", "与……保持一致", "至关重要", "深入探讨", "强调",
        "持久的", "增强", "培养", "获得", "突出", "相互作用",
        "复杂", "复杂性", "关键", "格局", "关键性的", "展示",
        "宝贵的", "充满活力的",
    ],
    "filler": [
        "值得注意的是", "为了实现这一目标", "在这个时间点",
        "由于……的事实", "在您需要帮助的情况下",
    ],
    "triple_pattern": [
        "不仅……而且", "这不仅仅是", "而是",
    ],
    "hedging": [
        "可以潜在地", "可能被认为", "可能会", "有些",
    ],
    "collaborative": [
        "希望这对您有帮助", "当然", "一定", "您说得完全正确",
        "请告诉我", "这是一个",
    ],
}


def _hermes_llm_call(prompt: str, system: str = "", timeout: int = 60) -> str:
    """通过 Hermes config 动态获取当前 provider 调用 LLM。

    读取 ~/.hermes/config.yaml 获取当前活跃的 provider/model/api_key。
    优先用 curl 直接调用 API（避免 Python SDK 依赖）。
    """
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.isfile(config_path):
        # fallback: 返回原文本（不处理）
        return ""

    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except Exception:
        return ""

    # 获取当前模型配置
    model_cfg = cfg.get("model", {})
    provider_name = cfg.get("provider", "opencode-go")
    api_key = ""
    base_url = "https://opencode.ai/zen/go/v1"

    # 从 providers 中查找 key
    providers = cfg.get("providers", {})
    if provider_name in providers:
        pcfg = providers[provider_name]
        api_key = pcfg.get("api_key", "")
        base_url = pcfg.get("base_url", base_url)
    else:
        # 尝试从环境变量取
        api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return ""

    model = model_cfg.get(provider_name, "deepseek-v4-flash")

    payload = {
        "model": model,
        "messages": [],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    if system:
        payload["messages"].append({"role": "system", "content": system})
    payload["messages"].append({"role": "user", "content": prompt})

    try:
        r = subprocess.run(
            [
                "curl", "-s", "--max-time", str(timeout),
                "-H", f"Authorization: Bearer {api_key}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload),
                f"{base_url}/chat/completions",
            ],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if r.returncode != 0:
            return ""
        data = json.loads(r.stdout)
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        return ""


def _detect_patterns(text: str) -> dict:
    """快速扫描文本中包含的 AI 写作模式。"""
    hits = {}
    for pattern_name, phrases in AI_PATTERNS.items():
        found = [p for p in phrases if p in text]
        if found:
            hits[pattern_name] = found
    return hits


def humanize_text(
    title: str,
    body: str,
    profile: str = "default",
    style_hint: str = "",
) -> dict:
    """对文章正文进行 AI 写作痕迹去除。

    Args:
        title: 文章标题
        body: 文章正文
        profile: 写作风格配置
        style_hint: 风格提示（如：科技/教育/营销）

    Returns:
        dict with keys:
            - ok: bool
            - title: 改写后标题
            - body: 改写后正文
            - patterns_detected: 检测到的 AI 模式
            - score: 质量评分 (0-50)
            - error: 错误信息（如有）
    """
    # 1. 检测 AI 模式
    title_hits = _detect_patterns(title)
    body_hits = _detect_patterns(body)
    combined_hits = {}
    for k in set(list(title_hits.keys()) + list(body_hits.keys())):
        combined_hits[k] = list(
            set(title_hits.get(k, []) + body_hits.get(k, []))
        )

    if not combined_hits:
        # 没有检测到 AI 模式，直接返回
        return {
            "ok": True,
            "title": title,
            "body": body,
            "patterns_detected": {},
            "score": 50,
        }

    # 2. 构造 Humanizer-zh 提示词
    pattern_summary = "\n".join(
        f"- **{k}**: {', '.join(v)}"
        for k, v in combined_hits.items()
    )

    sys_prompt = (
        "你是一位专业的中文文字编辑，擅长去除 AI 生成文本的痕迹。"
        "根据 Humanizer-zh（24 条 AI 写作检测规则）重写文本，"
        "使其听起来更自然、更有人味。\n\n"
        "核心原则：\n"
        "1. 删除填充短语和开场白\n"
        "2. 打破公式结构（三段式法则、否定式排比）\n"
        "3. 变化句子节奏，长短交错\n"
        "4. 直接陈述事实，跳过过度解释\n"
        "5. 删除听起来像 AI 金句的表述\n"
        "6. 注入真实个性：有观点、有态度、有具体细节\n"
        "7. 信任读者智慧，不手把手引导"
    )

    style_guide = f"目标风格：{style_hint}\n" if style_hint else ""

    prompt = f"""请重写以下文章，去除 AI 写作痕迹。

## 检测到的 AI 模式
{pattern_summary}

## 原文标题
{title}

## 原文正文
{body[:6000]}

{style_guide}
## 要求
请输出 JSON 格式（严格 JSON，不要 markdown 代码块）：
{{
  "title": "改写后的标题",
  "body": "改写后的正文",
  "changes": ["简要说明每项关键更改"],
  "score": 总分(0-50，按直接性/节奏/信任度/真实性/精炼度各10分)
}}"""

    result_text = _hermes_llm_call(prompt, sys_prompt)
    if not result_text:
        # LLM call failed — return original
        return {
            "ok": True,
            "title": title,
            "body": body,
            "patterns_detected": combined_hits,
            "score": 35,
            "error": "LLM call failed, returning original",
        }

    # 3. 解析 LLM 返回
    try:
        # 清理可能的 markdown 包装
        clean = result_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1]
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()

        data = json.loads(clean)
        return {
            "ok": True,
            "title": data.get("title", title),
            "body": data.get("body", body),
            "patterns_detected": combined_hits,
            "changes": data.get("changes", []),
            "score": data.get("score", 35),
        }
    except (json.JSONDecodeError, KeyError):
        # 解析失败，保留原文本
        return {
            "ok": True,
            "title": title,
            "body": body,
            "patterns_detected": combined_hits,
            "score": 35,
            "error": "failed to parse LLM response",
        }
