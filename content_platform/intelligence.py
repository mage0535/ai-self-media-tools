import json
import re
import urllib.request
from html import unescape
from .paths import trend_cache_dir
from pathlib import Path


def _plain(text):
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_url(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": "HermesContentPlatform/3.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode(errors="replace")


def collect_reference_posts(brief, limit=3):
    brief = brief or {}
    posts = []
    for row in brief.get("reference_posts", []):
        if isinstance(row, dict) and (row.get("title") or row.get("body")):
            posts.append({"title": str(row.get("title", "")), "body": str(row.get("body", "")), "source": row.get("source", "reference")})
    if posts:
        return posts[:limit]
    keywords = [str(word).casefold() for word in brief.get("keywords", []) if str(word).strip()]
    trend_dir = Path(brief.get("trend_cache_dir", str(trend_cache_dir())))
    if trend_dir.exists():
        files = sorted(trend_dir.glob("trending_*.json"), reverse=True)
        if files:
            try:
                payload = json.loads(files[0].read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else payload.get("trends", payload.get("items", []))
                for row in rows:
                    title = str(row.get("title", ""))
                    url = str(row.get("url", ""))
                    if not url:
                        continue
                    if keywords and not any(word in title.casefold() for word in keywords):
                        continue
                    try:
                        html = _fetch_url(url)
                    except Exception:
                        continue
                    body = _plain(html)[:4000]
                    if title or body:
                        posts.append({"title": title[:160], "body": body, "source": row.get("source", url)})
                    if len(posts) >= limit:
                        return posts[:limit]
            except Exception:
                pass
    for url in brief.get("sources", [])[:limit]:
        try:
            html = _fetch_url(url)
        except Exception:
            continue
        title = ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if title_match:
            title = _plain(title_match.group(1))
        body = _plain(html)[:4000]
        if title or body:
            posts.append({"title": title[:160], "body": body, "source": url})
    return posts[:limit]


def analyze_reference_posts(posts):
    posts = [row for row in (posts or []) if row.get("title") or row.get("body")]
    formats = set()
    cta = ""
    emoji_hits = 0
    opening_patterns = []
    paragraph_lengths = []
    for row in posts:
        body = str(row.get("body", ""))
        title = str(row.get("title", ""))
        if re.search(r"(^|\n)\s*\d+[.、]", body):
            formats.add("listicle")
        if "## " in body or re.search(r"(^|\n)\s*##\s+", body):
            formats.add("sectioned")
        if "?" in title or "？" in title:
            formats.add("question_hook")
        if any(token in body for token in ["建议收藏", "评论区", "转发给", "关注我", "留言"]):
            cta = next((token for token in ["评论区聊聊", "建议收藏", "转发给朋友", "关注我"] if token in body), cta or body[-12:])
        emoji_hits += len(re.findall(r"[\U0001F300-\U0001FAFF]", body))
        first_sentence = re.split(r"[。！？!?]", body.strip(), maxsplit=1)[0].strip()
        if first_sentence:
            opening_patterns.append(first_sentence[:50])
        paragraph_lengths.extend(len(part.strip()) for part in re.split(r"\n\s*\n", body) if part.strip())
    return {
        "sample_count": len(posts),
        "formats": sorted(formats),
        "cta": cta or "建议收藏备用",
        "emoji_density": round(emoji_hits / max(1, len(posts)), 2),
        "opening_patterns": opening_patterns[:3],
        "paragraph_length_hint": int(sum(paragraph_lengths) / max(1, len(paragraph_lengths))) if paragraph_lengths else 80,
    }


def build_generation_context(topic, brief):
    brief = brief or {}
    references = collect_reference_posts(brief)
    style = analyze_reference_posts(references)
    trend_stage = brief.get("trend_stage", "emerging")
    trend_angle = brief.get("trend_angle", "")
    reference_titles = [row.get("title", "") for row in references if row.get("title")]
    image_prompt = f"{topic}，{brief.get('niche', '')}，{brief.get('audience', '')}，可视化重点，图文并茂，信息密度高，适合社交平台封面"
    video_prompt = f"{topic}，先给强钩子，再拆 3 个关键点，末尾给行动建议，适合短视频脚本"
    return {
        "trend_stage": trend_stage,
        "trend_angle": trend_angle,
        "reference_titles": reference_titles[:5],
        "style": style,
        "image_prompt": image_prompt,
        "video_prompt": video_prompt,
        "hashtags": brief.get("keywords", [])[:6],
    }


def prompt_brief(topic, brief):
    context = build_generation_context(topic, brief)
    return json.dumps(
        {
            "topic": topic,
            "brief": brief,
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
        },
        ensure_ascii=False,
    )
