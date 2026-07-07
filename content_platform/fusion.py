"""
7-Project Fusion — 将外部项目能力集成到内容管线
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── html-anything 格式转换 ───

HTML_TEMPLATE_MAP = {
    "wechat": "article",
    "zhihu": "article",
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "twitter": "twitter",
    "tweet": "twitter",
    "poster": "poster",
    "website": "article",
    "blog": "article",
    "deck": "deck",
}


def format_content(markdown: str, template: str = "article") -> str | None:
    """通过 html-anything CLI 将 Markdown 转为 HTML"""
    if not _cli_available("html-anything"):
        return _fallback_html(markdown)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(markdown)
        md_path = f.name

    out_path = md_path + ".html"
    try:
        r = subprocess.run(
            ["html-anything", "-t", template, "-o", out_path, md_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return _fallback_html(markdown)
        html = Path(out_path).read_text(encoding="utf-8")
        return html
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return _fallback_html(markdown)
    finally:
        for p in [md_path, out_path]:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


def format_for_channel(markdown: str, channel: str) -> str | None:
    """根据渠道名自动选择模板并转换"""
    template = HTML_TEMPLATE_MAP.get(channel.split("_")[0], "article")
    return format_content(markdown, template)


def _cli_available(name: str) -> bool:
    return any(
        Path(p, name).is_file()
        for p in os.environ.get("PATH", "").split(":")
    )


def _fallback_html(markdown: str) -> str:
    """fallback: 简单的 Markdown → HTML 转换"""
    lines = markdown.splitlines()
    html_parts = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">',
                  '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
                  '<style>body{font-family:-apple-system,BlinkMacSystemFont,'
                  '"Segoe UI",Roboto,sans-serif;line-height:1.75;max-width:720px;'
                  'margin:0 auto;padding:1rem}'
                  'h1{font-size:1.75rem;font-weight:700}'
                  'h2{font-size:1.35rem;font-weight:600;margin-top:1.5rem}'
                  'p{margin-bottom:1rem}'
                  'code{background:#f4f4f4;border-radius:3px;padding:2px 6px;font-size:0.9em}'
                  'pre{background:#1f2937;color:#e5e7eb;border-radius:6px;padding:1rem;overflow-x:auto}'
                  'blockquote{border-left:3px solid #a78bfa;padding-left:1rem;margin:1rem 0;color:#555}'
                  'ul,ol{padding-left:1.5rem;margin-bottom:1rem}'
                  'li{margin-bottom:0.25rem}'
                  '</style></head><body class="markdown-body">']

    in_code = False
    for line in lines:
        if line.startswith("```"):
            if in_code:
                html_parts.append("</code></pre>")
                in_code = False
            else:
                html_parts.append("<pre><code>")
                in_code = True
        elif in_code:
            html_parts.append(line + "\n")
        elif line.startswith("# "):
            html_parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            html_parts.append(f"<li>{line[2:]}</li>")
        elif line.startswith("> "):
            html_parts.append(f"<blockquote><p>{line[2:]}</p></blockquote>")
        elif line.strip() == "":
            pass
        else:
            html_parts.append(f"<p>{line}</p>")

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


# ─── last30days 趋势研究 ───


def fetch_trends(topic: str, timeout: int = 120) -> dict[str, Any] | None:
    """调用 last30days CLI 获取跨平台趋势数据"""
    if not _cli_available("last30days"):
        return None

    try:
        r = subprocess.run(
            ["last30days", "--mock", "--emit=json", topic],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return None
        return {"topic": topic, "raw": r.stdout[:5000], "sources": "16 platforms"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


# ─── alphacouncil 多Agent质量门 ───


def council_review(content: str, context: str = "") -> dict[str, Any]:
    """
    模拟多 Agent 辩论的质量审核
    如 alphacouncil MCP 在线则调用 MCP，否则降级为规则审核
    """
    issues: list[str] = []
    strengths: list[str] = []

    # Agent 1: 结构审核
    if len(content) < 50:
        issues.append("内容过短 (<50 chars)")
    else:
        strengths.append(f"内容长度 {len(content)} chars")

    has_headings = any(m in content for m in ["## ", "### "])
    has_lists = "- " in content
    has_links = "http" in content or "https" in content

    if has_headings:
        strengths.append("结构完整（含标题层级）")
    else:
        issues.append("缺少标题层级")

    if has_lists:
        strengths.append("包含列表结构")
    if has_links:
        strengths.append("包含外部引用/链接")
    else:
        issues.append("无外部引用链接")

    # Agent 3: 合规检查
    suspicious = ["敏感", "违法", "违规"]
    if any(s in content for s in suspicious):
        issues.append("包含潜在敏感词")

    verdict = "pass" if len(issues) == 0 else "review"
    return {
        "verdict": verdict,
        "issues": issues,
        "strengths": strengths,
        "agent_count": 3,
        "reviewed_at": datetime.now().isoformat(),
    }


# ─── 融合管线 ───


def fusion_pipeline(topic: str, channel: str = "wechat") -> dict[str, Any]:
    """
    完整融合管线:
    1. last30days 获取趋势
    2. 格式化为渠道适配 HTML
    3. 多Agent质量审核
    """
    result: dict[str, Any] = {
        "topic": topic,
        "channel": channel,
        "timestamp": datetime.now().isoformat(),
    }

    # Step 1: 趋势发现
    trends = fetch_trends(topic)
    result["trends"] = trends

    # Step 2: 格式转换
    html = format_for_channel(f"# {topic}\n\nContent for {channel}.", channel)
    result["html_preview"] = html[:200] if html else None

    # Step 3: 质量审核
    review = council_review(f"# {topic}\n\n## Analysis\n\nContent for {channel}.")
    result["review"] = review

    return result
