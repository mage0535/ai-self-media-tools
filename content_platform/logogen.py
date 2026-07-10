"""
logogen.py — 归藏 logo-generator-skill 的 SVG Logo 生成桥接。

基于归藏 logo-generator-skill 的设计范式和 SVG 最佳实践，
为品牌/产品生成专业的 SVG Logo 变体。

集成方式：
    from .logogen import generate_logo
    result = generate_logo(name, industry, concept)
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# 归藏 logo-generator 设计范式的 SVG 模式模板
LOGO_PATTERNS = {
    "concentric_dots": """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .dot {{ fill: {color}; opacity: {opacity}; }}
    </style>
  </defs>
  {dots}
</svg>""",

    "geometric_shield": """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <polygon points="{points}" fill="none" stroke="{color}" stroke-width="2"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>
</svg>""",

    "node_network": """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <path d="{path}" stroke="{color}" stroke-width="1.5" fill="none"/>
  {nodes}
</svg>""",

    "letter_mark": """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <text x="50" y="65" text-anchor="middle" font-family="{font}" font-size="{size}"
        font-weight="{weight}" fill="{color}" letter-spacing="{spacing}">{letter}</text>
</svg>""",

    "abstract_shape": """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <path d="{path}" fill="{color}" opacity="{opacity}"/>
  {accent}
</svg>""",
}


def _hermes_llm_call(prompt: str, system: str = "", timeout: int = 120) -> str:
    """调用 Hermes 当前 provider 生成 Logo SVG。"""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.isfile(config_path):
        return ""

    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except Exception:
        return ""

    model_cfg = cfg.get("model", {})
    provider_name = cfg.get("provider", "opencode-go")
    api_key = ""
    base_url = "https://opencode.ai/zen/go/v1"

    providers = cfg.get("providers", {})
    if provider_name in providers:
        pcfg = providers[provider_name]
        api_key = pcfg.get("api_key", "")
        base_url = pcfg.get("base_url", base_url)
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return ""

    model = model_cfg.get(provider_name, "deepseek-v4-flash")

    payload = {
        "model": model,
        "messages": [],
        "temperature": 0.4,
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


def generate_logo(
    name: str,
    industry: str = "",
    concept: str = "",
    style: str = "minimal",
    color: str = "#000000",
    output_dir: str = "",
) -> dict:
    """为品牌/产品生成 SVG Logo 变体。

    Args:
        name: 品牌/产品名称
        industry: 行业（如 AI, fintech, education）
        concept: 核心概念（如 connection, flow, security）
        style: minimal/complex
        color: 主色调（hex）
        output_dir: 输出目录（默认 artifacts 目录）

    Returns:
        dict with keys:
            - ok: bool
            - variants: list of {name, svg, path, rationale}
            - error: str
    """
    out = Path(output_dir) if output_dir else Path("logo_output")
    out.mkdir(parents=True, exist_ok=True)

    sys_prompt = (
        "你是专业的 Logo 设计师。生成纯 SVG 代码的设计方案。\n"
        "遵循以下设计原则：\n"
        "1. 使用 viewBox=\"0 0 100 100\" 确保一致性\n"
        "2. 使用 currentColor 确保灵活配色\n"
        "3. 保持代码简洁清晰\n"
        "4. 相同概念，6 种不同的视觉方向\n"
        "5. SVG 必须是合法、自包含的 XML"
    )

    prompt = f"""为以下品牌/产品生成 6 个不同的 SVG Logo 设计方案：

品牌名称：{name}
行业：{industry or '通用'}
核心概念：{concept or '简洁专业'}
风格偏好：{style}
主色调：{color}

请输出严格 JSON 格式（不要 markdown 代码块）：
{{
  "variants": [
    {{
      "name": "方案1名称（如：极简文字标）",
      "svg": "<svg viewBox=...>完整 SVG 代码</svg>",
      "rationale": "设计理念说明"
    }},
    ...
  ]
}}

每个方案必须：
- 使用 viewBox="0 0 100 100"
- 使用 currentColor 作为填充/描边色
- 6 种方案视觉方向各不相同（文字标/图形标/组合标/抽象标/线标/面标）
"""

    result = _hermes_llm_call(prompt, sys_prompt)
    if not result:
        return {"ok": False, "variants": [], "error": "LLM call failed"}

    # 解析 JSON
    try:
        clean = result.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1]
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()
        data = json.loads(clean)
    except (json.JSONDecodeError, KeyError):
        return {"ok": False, "variants": [], "error": "failed to parse LLM response"}

    variants = data.get("variants", [])
    if not variants or not isinstance(variants, list):
        return {"ok": False, "variants": [], "error": "no valid variants in response"}

    results = []
    for i, v in enumerate(variants):
        svg_text = v.get("svg", "")
        if not svg_text:
            continue
        # 用 name 做文件名
        safe_name = re.sub(r'[^\u4e00-\u9fff\w-]', '', v.get("name", f"variant-{i+1}"))[:40]
        if not safe_name:
            safe_name = f"logo-{i+1}"
        fname = f"logo-{safe_name}.svg"
        path = out / fname
        # 注入 currentColor 替换显式颜色（如果适用）
        if color and color != "#000000" and color not in svg_text:
            svg_text = svg_text.replace('currentColor', color)
        path.write_text(svg_text, encoding="utf-8")
        results.append({
            "name": v.get("name", f"Variant {i+1}"),
            "svg": svg_text,
            "path": str(path),
            "rationale": v.get("rationale", ""),
            "checksum": hashlib.sha256(svg_text.encode()).hexdigest(),
        })

    return {
        "ok": True,
        "variants": results,
        "count": len(results),
        "output_dir": str(out),
    }
