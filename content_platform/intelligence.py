import json
import re
import urllib.request
from html import unescape
from pathlib import Path

from .niche_analysis import analyze_niche
from .paths import trend_cache_dir
from .sources import normalize_source_items, summarize_source_items
from .strategy_router import choose_content_strategy
from .viral_score import score_topic_candidate


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
            posts.append(
                {
                    "title": str(row.get("title", "")),
                    "body": str(row.get("body", "")),
                    "source": row.get("source", "reference"),
                    "account_handle": str(row.get("account_handle", "")),
                    "platform": str(row.get("platform", "")),
                    "url": str(row.get("url", "")),
                }
            )
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
                        posts.append(
                            {
                                "title": title[:160],
                                "body": body,
                                "source": row.get("source", url),
                                "account_handle": str(row.get("account_handle", "")),
                                "platform": str(row.get("platform", "")),
                                "url": url,
                            }
                        )
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
            posts.append({"title": title[:160], "body": body, "source": url, "account_handle": "", "platform": "", "url": url})
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
        if re.search(r"(^|\n)\s*\d+[.)]", body):
            formats.add("listicle")
        if "## " in body or re.search(r"(^|\n)\s*##\s+", body):
            formats.add("sectioned")
        if "?" in title or "？" in title:
            formats.add("question_hook")
        for token in ("Save this", "Follow", "Comment", "收藏", "关注", "评论"):
            if token.casefold() in body.casefold():
                cta = token
                break
        emoji_hits += len(re.findall(r"[\U0001F300-\U0001FAFF]", body))
        first_sentence = re.split(r"[。！？.!?]", body.strip(), maxsplit=1)[0].strip()
        if first_sentence:
            opening_patterns.append(first_sentence[:50])
        paragraph_lengths.extend(len(part.strip()) for part in re.split(r"\n\s*\n", body) if part.strip())
    return {
        "sample_count": len(posts),
        "formats": sorted(formats),
        "cta": cta or "Save this",
        "emoji_density": round(emoji_hits / max(1, len(posts)), 2),
        "opening_patterns": opening_patterns[:3],
        "paragraph_length_hint": int(sum(paragraph_lengths) / max(1, len(paragraph_lengths))) if paragraph_lengths else 80,
    }


def build_generation_context(topic, brief):
    brief = brief or {}
    references = collect_reference_posts(brief)
    source_catalog = normalize_source_items(topic, brief, references)
    source_summary = summarize_source_items(source_catalog)
    style = analyze_reference_posts(references)
    niche_report = analyze_niche(topic, source_catalog or references)
    viral_score = score_topic_candidate(topic, brief, references, niche_report)
    strategy = choose_content_strategy(topic, brief, viral_score, niche_report)
    trend_stage = brief.get("trend_stage", viral_score["trend_stage"])
    trend_angle = brief.get("trend_angle", "")
    reference_titles = [row.get("title", "") for row in references if row.get("title")]
    audience = str(brief.get("audience", "")).strip()
    niche = str(brief.get("niche", "")).strip()

    # 可选：Open Notebook 深度研究
    on_research = {}
    if brief.get("deep_research"):
        try:
            from scripts.open_notebook_integrator import research_topic
            urls = brief.get("deep_research_urls", [])
            texts = brief.get("deep_research_texts", [])
            if urls or texts:
                on_research = research_topic(topic, urls=urls, texts=texts)
        except Exception:
            on_research = {"error": "open_notebook unavailable"}

    content_form = strategy["content_form"]
    image_prompt = f"{topic} | niche={niche} | audience={audience} | form={content_form} | create a strong cover with high information density"
    video_prompt = f"{topic} | form={content_form} | start with a hook, explain three points, end with a CTA"
    # 配音脚本生成指南（传给生成器）
    narration_guide = (
        f"生成中文配音脚本。跟踪赛道(niche={niche})和内容形式({content_form})自动适配风格。"
        "单人播报模式：直接输出配音文本。"
        "多人对话模式：使用[角色A]台词\\n[角色B]台词格式标记不同说话人。"
    )
    return {
        "trend_stage": trend_stage,
        "trend_angle": trend_angle,
        "reference_titles": reference_titles[:5],
        "style": style,
        "image_prompt": image_prompt,
        "video_prompt": video_prompt,
        "narration_guide": narration_guide,
        "hashtags": brief.get("keywords", [])[:6],
        "source_catalog": source_catalog,
        "source_summary": source_summary,
        "niche_report": niche_report,
        "viral_score": viral_score,
        "strategy": strategy,
        "open_notebook_research": on_research,
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
            "source_summary": context["source_summary"],
            "niche_report": context["niche_report"],
            "viral_score": context["viral_score"],
            "strategy": context["strategy"],
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "narration_guide": context.get("narration_guide", ""),
            "open_notebook_research": context.get("open_notebook_research", {}),
        },
        ensure_ascii=False,
    )
