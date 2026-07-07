"""
SEO/GEO module — keyword research, SERP analysis, and GEO quality checks.

Standalone module usable by any pipeline. No Hermes dependency.
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime


GEO_CHECK_DEFAULTS = {
    "claims_with_numbers": {"weight": 2, "desc": "每个关键声明都有具体数字支持"},
    "claims_with_sources": {"weight": 2, "desc": "重要声明标注来源链接"},
    "authority_quotes": {"weight": 1, "desc": "使用引号/引用块标注权威引用"},
    "direct_answer": {"weight": 2, "desc": "前200字直接回答读者核心问题"},
    "short_paragraphs": {"weight": 1, "desc": "段落不超过3-4句"},
    "structured_list": {"weight": 1, "desc": "至少1个对比表或结构化列表"},
    "faq_section": {"weight": 1, "desc": "包含FAQ格式的答案块"},
    "total": {"weight": 10, "desc": ""},
}


def geo_check(text, checks=None):
    """
    GEO 7-point quality checklist for AI engine visibility (KDD 2024 / ICLR 2026).

    Returns: {"score": 0-100, "checks": {name: bool, ...}, "details": {name: str, ...}}
    """
    if checks is None:
        checks = list(GEO_CHECK_DEFAULTS.keys())[:-1]

    s = text.lower()
    results = {}
    details = {}

    for check in checks:
        ok = False
        detail = ""

        if check == "claims_with_numbers":
            nums = re.findall(r'\d+[%万亿美元元]?', s)
            ok = len(set(nums)) >= 3
            detail = f"发现 {len(set(nums))} 个独立数字" if ok else f"仅 {len(set(nums))} 个数字，需≥3"

        elif check == "claims_with_sources":
            url_count = len(re.findall(r'https?://[^\s)]+', s))
            paren_refs = len(re.findall(r'\([^)]{3,}20\d{2}[^)]*\)', s))
            has_source_words = any(w in s for w in ["来源", "source", "according", "报告", "数据", "research"])
            ok = url_count >= 1 or paren_refs >= 1 or has_source_words
            detail = f"URL={url_count} 引用={paren_refs} 来源词={has_source_words}"

        elif check == "authority_quotes":
            quotes = re.findall(r'"[^"]{40,}"', text)
            blockquotes = len(re.findall(r'^\s*>', text, re.MULTILINE))
            ok = len(quotes) >= 1 or blockquotes >= 1
            detail = f"引号={len(quotes)} 引用块={blockquotes}"

        elif check == "direct_answer":
            first200 = text[:200]
            ok = bool(re.search(r'[？?]|如何|怎样|whereby|how to|what is', first200, re.I)) or len(first200) >= 100
            detail = f"前200字={'有' if ok else '无'}直接回答"

        elif check == "short_paragraphs":
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            long_count = 0
            for l in lines:
                zh_sents = max(1, len(re.split(r'[。！？]', l)))
                en_sents = max(1, len(re.split(r'[.!?]\s', l)))
                sents = max(zh_sents, en_sents)
                if sents > 4:
                    long_count += 1
            ok = long_count == 0
            detail = f"长段落={long_count}/{len(lines)}行"

        elif check == "structured_list":
            has_table = '|' in text and '---' in text
            has_list = bool(re.search(r'^\s*[-*\d+.]\s', text, re.MULTILINE))
            ok = has_table or has_list
            detail = f"表格={'是' if has_table else '否'} 列表={'是' if has_list else '否'}"

        elif check == "faq_section":
            q_count = len(re.findall(r'(?:^|\s)Q\s*[：:]|\*\*Q[^：:]*[：:]|\d+\.\s+[^。！？\n]*?[？?]', text, re.MULTILINE))
            a_count = len(re.findall(r'(?:^|\s)A\s*[：:]|\*\*A[^：:]*[：:]|\*\*答[：:]', text, re.MULTILINE))
            qm_count = len(re.findall(r'[？?]', text))
            ok = q_count >= 1 or a_count >= 1 or qm_count >= 3
            detail = f"Q标记={q_count} A标记={a_count} 问号={qm_count}"

        results[check] = ok
        details[check] = detail

    total_weight = 0
    weighted = 0
    for check in checks:
        w = GEO_CHECK_DEFAULTS.get(check, {}).get("weight", 1)
        total_weight += w
        if results[check]:
            weighted += w

    score = round(weighted / total_weight * 100) if total_weight else 0
    return {"score": score, "checks": results, "details": details}


def openserp_search(query, engine="duck", limit=10, endpoint="", api_key=""):
    """
    Search via OpenSERP instance. Returns SERP results with structure analysis.
    endpoint: e.g. "http://your-vps:7000/search"
    """
    if not endpoint:
        endpoint = os.environ.get("OPENSERP_ENDPOINT", "http://localhost:7000/search")
    if not api_key:
        api_key = os.environ.get("OPENSERP_API_KEY", "")

    params = urllib.parse.urlencode({
        "q": query, "engine": engine, "limit": limit, "api_key": api_key,
    })
    url = f"{endpoint.rstrip('/')}?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-self-media-tools/3.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return {"error": str(exc), "results": []}

    results = data.get("results", [])
    if not results:
        return {"error": "no results", "results": []}

    types = {}
    for r in results:
        t = r.get("type", "organic")
        types[t] = types.get(t, 0) + 1

    people_also_ask = data.get("people_also_ask", [])
    related = data.get("related_searches", [])

    return {
        "query": query,
        "engine": engine,
        "result_count": len(results),
        "serp_types": types,
        "results": [{"title": r.get("title", ""), "url": r.get("url", ""),
                      "snippet": r.get("snippet", "")[:200]} for r in results[:limit]],
        "people_also_ask": people_also_ask,
        "related_searches": related,
        "content_gaps": _find_content_gaps(results),
    }


def _find_content_gaps(results):
    gaps = []
    if "comparison" not in str(results).lower() and "vs" not in str(results).lower():
        gaps.append("缺少横向对比类型内容")
    top_titles = [r.get("title", "").lower() for r in results[:5]]
    product_words = sum(1 for t in top_titles if any(w in t for w in ["best", "top", "review", "pricing"]))
    if product_words >= 3:
        gaps.append("SERP被产品页占据，缺少深度教程或对比指南")
    if not any("how to" in t or "tutorial" in t or "guide" in t for t in top_titles):
        gaps.append("缺少教程/指南类内容")
    return gaps


def seo_analyze(url, timeout=30):
    """
    Run pyseoanalyzer on a URL. Requires pyseoanalyzer installed.
    Returns: {"title": ..., "description": ..., "issues": [...], "keywords": [...]}
    """
    try:
        from seo_analyzer import analyze
        result = analyze(url)
    except ImportError:
        try:
            proc = subprocess.run(
                ["seo-analyze", url],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            return {"cli_output": proc.stdout[:2000], "error": proc.stderr[:500] if proc.returncode else ""}
        except FileNotFoundError:
            return {"error": "pyseoanalyzer not installed. Run: pip install pyseoanalyzer"}
        except Exception as exc:
            return {"error": str(exc)}
    except Exception as exc:
        return {"error": str(exc)}

    if isinstance(result, dict):
        return {
            "title": result.get("title", ""),
            "description": result.get("meta_description", ""),
            "keywords": result.get("keywords", []),
            "issues": result.get("issues", []),
            "word_count": result.get("word_count", 0),
        }
    return {"error": "unknown format"}


def format_geo_report(text, label="content"):
    result = geo_check(text)
    lines = [f"## GEO 检查报告 — {label}", ""]
    lines.append(f"**综合评分: {result['score']}/100**")
    lines.append("")
    for check, ok in result["checks"].items():
        icon = "✅" if ok else "❌"
        desc = GEO_CHECK_DEFAULTS.get(check, {}).get("desc", check)
        detail = result["details"].get(check, "")
        lines.append(f"{icon} **{desc}** — {detail}")
    lines.append("")
    if result["score"] >= 85:
        lines.append("**结论**: AI 可见度优化通过 ✅")
    elif result["score"] >= 60:
        lines.append("**结论**: 部分通过，需改进红色项 ⚠️")
    else:
        lines.append("**结论**: 未通过，需要重写 ❌")
    return "\n".join(lines)


# -- v3.3 compatibility aliases --
search = openserp_search
analyze = seo_analyze
geo_checklist = geo_check
