#!/usr/bin/env python3
"""
GitHub Star Explorer - discovers trending GitHub projects and generates promotional content.
Data source: GitHub Search API. Output adapted for promo_pipeline content templates.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def log(msg):
    print(f"[GitHubStar] {datetime.now(CST).strftime('%H:%M:%S')} {msg}")


def fetch_trending(language="python", since="daily"):
    query = f"created:>{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": 10})
    url = f"https://api.github.com/search/repositories?{params}"

    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"User-Agent": "HermesContentPlatform/3.0", "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return [
            {
                "name": item["full_name"],
                "url": item["html_url"],
                "stars": item["stargazers_count"],
                "description": item.get("description") or "",
                "language": item.get("language") or "",
                "topics": item.get("topics", []),
            }
            for item in data.get("items", [])[:10]
        ]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:200]
        log(f"GitHub API rate limited or error: {exc.code} - {body}")
        return []
    except Exception as exc:
        log(f"GitHub API error: {exc}")
        return []


def generate_content(project, lang="zh"):
    en = {
        "title": f"GitHub Star Explorer: {project['name']}",
        "body": (
            f"\u2b50\ufe0f {project['stars']} stars\n\n"
            f"{project['description']}\n\n"
            f"Language: {project['language']}\n"
            f"Topics: {', '.join(project['topics'][:5])}\n\n"
            f"{project['url']}"
        ),
    }
    zh = {
        "title": f"GitHub \u661f\u63a2: {project['name']}",
        "body": (
            f"\u2b50\ufe0f {project['stars']} \u661f\n\n"
            f"{project['description']}\n\n"
            f"\u8bed\u8a00: {project['language']}\n"
            f"\u6807\u7b7e: {', '.join(project['topics'][:3])}\n\n"
            f"\U0001f517 {project['url']}"
        ),
    }
    return zh if lang == "zh" else en


def quality_check(project):
    if not project:
        return {"pass": False, "reason": "Empty project"}
    stars = project.get("stars", 0) or 0
    desc = project.get("description") or ""
    if stars < 10:
        return {"pass": False, "reason": "Too few stars: " + str(stars)}
    if not desc or len(desc) < 10:
        return {"pass": False, "reason": "No meaningful description"}
    return {"pass": True}


def daily_pick(lang="en"):
    projects = fetch_trending()
    if not projects:
        return None
    # Filter by quality, pick top
    for p in projects:
        if quality_check(p)["pass"]:
            content = generate_content(p, lang)
            return {
                "project": p,
                "content": content,
                "generated_at": datetime.now(CST).isoformat(),
            }
    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GitHub Star Explorer")
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    args = parser.parse_args()

    result = daily_pick(args.lang)
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"error": "No projects found (API may be rate-limited)"}))
