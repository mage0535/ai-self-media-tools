"""
SEO Tools Module — OpenSERP SERP data + pyseoanalyzer technical SEO
Integrated into ai-self-media-tools v3.3.0.

Usage:
    python -m content_platform seo-search <query> [--engine duck|google|bing|baidu] [--limit 5]
    python -m content_platform seo-analyze <url> [--check]
"""
import json
import subprocess
import sys
from pathlib import Path
from urllib import request, parse, error

from .models import DeliveryResult

OPENSERP_VPS = "{{OPENSERP_HOST}}"
OPENSERP_ENGINES = ("google", "bing", "duck", "baidu", "yandex", "ecosia")


def _openserp_request(engine, text, limit=5):
    """Call OpenSERP VPS for structured SERP data."""
    url = f"http://{OPENSERP_VPS}/{engine}/search?text={parse.quote(text)}&limit={limit}"
    try:
        req = request.Request(url, headers={"User-Agent": "HermesContentPlatform/3.3"})
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data
    except Exception as exc:
        return {"error": str(exc), "query": {"text": text, "engine": engine}}


def search(query, engine="duck", limit=5):
    """Search SERP via OpenSERP. Returns structured results."""
    engine = engine.lower()
    if engine not in OPENSERP_ENGINES:
        return {"error": f"unsupported engine: {engine}, choose from {OPENSERP_ENGINES}"}

    data = _openserp_request(engine, query, limit)
    if "error" in data:
        return data

    results = []
    for r in data.get("results", [])[:limit]:
        results.append({
            "rank": r.get("rank", 0),
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
        })

    return {
        "query": query,
        "engine": engine,
        "total_results": data.get("total_results", len(results)),
        "results": results,
        "people_also_ask": data.get("people_also_ask", []),
        "related_searches": data.get("related_searches", []),
    }


def analyze(url):
    """Run pyseoanalyzer technical SEO audit on a URL.

    Returns dict with title, word count, links, warnings.
    """
    try:
        from pyseoanalyzer import analyze as _pyseo_analyze
    except ImportError:
        return {"error": "pyseoanalyzer not installed. Run: pip install pyseoanalyzer"}

    try:
        output = _pyseo_analyze(url, sitemap_url=None)
        if isinstance(output, dict):
            return {
                "url": url,
                "title": output.get("title", "N/A"),
                "words": output.get("word_count", 0),
                "links": output.get("links", 0),
                "issues": output.get("issues", []),
                "keywords": output.get("keywords", []),
            }
        return {"url": url, "raw": str(output)[:2000]}
    except Exception as exc:
        return {"error": str(exc)}


def geo_checklist(draft):
    """Evaluate content against GEO 7-point checklist (KDD 2024 methodology).

    Returns a dict of checks and pass/fail.
    """
    body = (draft.get("title", "") + "\n" + draft.get("body", "")).lower()
    checks = {}

    # 1. Claims with numbers
    import re
    number_claims = len(re.findall(r'\d+[%]|\d+[倍]|\d+[个只家]|\d+[kK万]', body))
    checks["claims_with_numbers"] = number_claims >= 2

    # 2. Claims with sources
    source_indicators = ["研究", "报告", "根据", "数据", "arxiv", "据", "来源"]
    checks["claims_with_sources"] = any(ind in body for ind in source_indicators)

    # 3. FAQ/QA format
    checks["has_faq"] = "?" in body[:500] or "q:" in body or "问：" in body

    # 4. Comparison tables
    checks["has_table"] = "|" in body and "---" in body

    # 5. Summary at top
    first_100 = body[:100] if len(body) >= 100 else body
    checks["has_summary"] = "结果" in first_100 or "总结" in first_100 or "overview" in first_100

    # 6. Quoted data
    checks["has_quotes"] = '"' in body or "'" in body

    # 7. Structured lists
    checks["has_lists"] = "- " in body or "* " in body or re.search(r'^\d+\.', body, re.MULTILINE) is not None

    score = sum(1 for v in checks.values() if v) / len(checks) * 100
    return {"score": round(score, 1), "checks": checks}
