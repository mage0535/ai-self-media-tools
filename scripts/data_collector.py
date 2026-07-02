#!/usr/bin/env python3
"""
Data Collector - web scraping and content research engine.
Based on XCrawl pattern: crawl -> structure -> Excel/report.
Used by content_generator.py and promo_pipeline.py for topic research.
"""
import csv
import io
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def log(msg):
    print(f"[Collector] {datetime.now(CST).strftime('%H:%M:%S')} {msg}")


def scrape_urls(urls, timeout=15):
    if not HAS_REQUESTS:
        return [{"url": url, "error": "requests not installed"} for url in urls]
    results = []
    for url in urls[:20]:
        try:
            r = requests.get(url, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ContentResearchBot/1.0)"
            })
            results.append({"url": url, "status": r.status_code, "html": r.text[:5000]})
        except Exception as exc:
            results.append({"url": url, "error": str(exc)[:200]})
    return results


def to_excel(data, columns, output_path):
    if HAS_PANDAS and output_path.endswith(".xlsx"):
        df = pd.DataFrame(data, columns=columns)
        df.to_excel(output_path, index=False)
        return output_path
    csv_path = output_path.replace(".xlsx", ".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        if data:
            w.writerows(data)
    return csv_path


def generate_report(data_path):
    if HAS_PANDAS:
        df = pd.read_excel(data_path) if data_path.endswith(".xlsx") else pd.read_csv(data_path)
        return json.dumps({
            "rows": len(df),
            "columns": list(df.columns),
        }, indent=2)
    return "Report requires pandas"


def content_research(topic, max_sources=5):
    query = urllib.parse.quote(topic)
    search_urls = [
        f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&hitsPerPage=10",
        f"https://api.github.com/search/repositories?q={query}&sort=stars&per_page=5",
    ]
    results = scrape_urls(search_urls)
    data = []
    for r in results:
        if r.get("status") == 200:
            data.append({
                "source": r["url"][:80],
                "status": r["status"],
                "preview": r.get("html", "")[:200],
            })
    return {
        "topic": topic,
        "sources_found": len(data),
        "data": data,
        "report_ready": len(data) > 0,
    }


def quality_check(data):
    if not data or not data.get("data"):
        return {"pass": False, "reason": "No data collected"}
    sources = data.get("data", [])
    valid = sum(1 for s in sources if s.get("status") == 200)
    return {
        "pass": valid >= max(1, len(sources) * 0.3),
        "valid_sources": valid,
        "total_sources": len(sources),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Data Collector - content research engine")
    parser.add_argument("topic", nargs="?", default="AI agent", help="Topic to research")
    args = parser.parse_args()

    result = content_research(args.topic)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\nQuality:", json.dumps(quality_check(result)))
