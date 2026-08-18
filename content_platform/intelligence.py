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
from .viral_monitor import build_viral_report

GLOBAL_EN_PLATFORMS = {"devto", "buttondown", "writeas", "telegraph", "mastodon", "bluesky", "threads", "twitter", "x", "tiktok", "youtube", "nostr", "instagram"}
CN_PLATFORMS = {"wechat", "weixin", "wechat_official", "douyin", "xiaohongshu", "rednote", "bilibili", "kuaishou", "shipinhao", "juejin", "zhihu", "csdn"}


def infer_content_language(brief):
    brief = brief or {}
    explicit = str(brief.get("language") or brief.get("locale") or "").strip().lower()
    if explicit:
        if explicit.startswith(("en", "english")):
            return "en"
        if explicit.startswith(("zh", "cn", "chinese")) or "中文" in explicit:
            return "zh"
        return explicit[:16]
    platforms = [str(p).casefold() for p in brief.get("platforms", []) if str(p).strip()]
    if platforms and all(p in GLOBAL_EN_PLATFORMS for p in platforms):
        return "en"
    if any(p in CN_PLATFORMS for p in platforms):
        return "zh"
    return "zh"


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
                    "views": row.get("views", row.get("plays", row.get("impressions", 0))),
                    "likes": row.get("likes", 0),
                    "comments": row.get("comments", 0),
                    "shares": row.get("shares", row.get("reposts", 0)),
                    "saves": row.get("saves", row.get("favorites", 0)),
                    "followers": row.get("followers", row.get("account_followers", 0)),
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


def cluster_reference_topics(items):
    buckets = {}
    for item in items or []:
        signals = list(item.get("topic_signals", []))
        forms = list(item.get("content_forms", []))
        host = item.get("source_host", "")
        platform = item.get("platform", "")
        key_parts = signals[:2] or forms[:1] or [platform or host or "general"]
        cluster_key = "-".join(str(part).casefold() for part in key_parts if str(part).strip())[:80] or "general"
        bucket = buckets.setdefault(
            cluster_key,
            {
                "cluster_key": cluster_key,
                "label": key_parts[0] if key_parts else "general",
                "sample_count": 0,
                "platforms": set(),
                "source_hosts": set(),
                "topic_signals": set(),
                "content_forms": set(),
            },
        )
        bucket["sample_count"] += 1
        if platform:
            bucket["platforms"].add(platform)
        if host:
            bucket["source_hosts"].add(host)
        bucket["topic_signals"].update(signals)
        bucket["content_forms"].update(forms)
    clusters = []
    for bucket in buckets.values():
        clusters.append(
            {
                "cluster_key": bucket["cluster_key"],
                "label": bucket["label"],
                "score": round(min(1.0, 0.35 + bucket["sample_count"] * 0.12 + len(bucket["platforms"]) * 0.08), 3),
                "sample_count": bucket["sample_count"],
                "platforms": sorted(bucket["platforms"]),
                "source_hosts": sorted(bucket["source_hosts"]),
                "topic_signals": sorted(bucket["topic_signals"])[:8],
                "content_forms": sorted(bucket["content_forms"]),
            }
        )
    return sorted(clusters, key=lambda row: (-row["score"], row["cluster_key"]))


def build_generation_context(topic, brief):
    brief = brief or {}
    language = infer_content_language(brief)
    references = collect_reference_posts(brief)
    source_catalog = normalize_source_items(topic, brief, references)
    source_summary = summarize_source_items(source_catalog)
    topic_clusters = cluster_reference_topics(source_catalog)
    style = analyze_reference_posts(references)
    niche_report = analyze_niche(topic, source_catalog or references)
    viral_score = score_topic_candidate(topic, brief, references, niche_report)
    viral_growth_report = build_viral_report(source_catalog or references, brief.get("recent_by_account", {}))
    strategy = choose_content_strategy(topic, brief, viral_score, niche_report, viral_growth_report)
    trend_stage = brief.get("trend_stage", viral_score["trend_stage"])
    trend_angle = brief.get("trend_angle", "")
    reference_titles = [row.get("title", "") for row in references if row.get("title")]
    audience = str(brief.get("audience", "")).strip()
    niche = str(brief.get("niche", "")).strip()
    historical_feedback = brief.get("historical_feedback", {})
    cluster_memory = brief.get("cluster_memory", [])
    content_hygiene = brief.get("content_hygiene", {})
    cornerstone_mode = bool(content_hygiene and content_hygiene.get("recommended_action") in {"merge_into_cornerstone", "refresh_existing_cornerstone"})

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
    if language == "en":
        narration_guide = (
            f"Generate an English narration script. Adapt tone to niche={niche} and content_form={content_form}. "
            "Single-speaker mode: output narration text directly. Multi-speaker mode: use [Speaker A] lines."
        )
    else:
        narration_guide = (
            f"生成中文配音脚本。跟踪赛道(niche={niche})和内容形式({content_form})自动适配风格。"
            "单人播报模式：直接输出配音文本。"
            "多人对话模式：使用[角色A]台词\n[角色B]台词格式标记不同说话人。"
        )
    return {
        "language": language,
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
        "topic_clusters": topic_clusters,
        "niche_report": niche_report,
        "viral_score": viral_score,
        "viral_growth_report": viral_growth_report,
        "strategy": strategy,
        "historical_feedback": historical_feedback,
        "cluster_memory": cluster_memory,
        "open_notebook_research": on_research,
        "content_hygiene": content_hygiene,
        "cornerstone_mode": cornerstone_mode,
        # 2026-08-16：注入平台运营规则（收藏率权重/AI声明/新规等），生成器自动适配
        "platform_rules": _load_platform_rules(strategy),
        # 2026-08-16：注入平台可用钩子模板库，生成标题/脚本时参考爆款结构
        "hook_samples": _load_hook_samples(strategy.get("primary_platforms") or ""),
    }


def _load_platform_rules(strategy: dict) -> str:
    """按策略主平台加载 2026 规则浓缩文本；失败时静默返回空串（不阻断生成）。"""
    try:
        from .platform_rules import platform_rules_brief

        platforms = {str(p).casefold() for p in strategy.get("primary_platforms") or []}
        # douyin_ai/douyin_pet 映射到 douyin 规则；wechat_official 映射 gzh
        alias = {
            "douyin_ai": "douyin", "douyin_pet": "douyin",
            "wechat_official": "gzh", "weixin": "gzh", "rednote": "xhs",
        }
        platform = next(
            (alias.get(p, p) for p in platforms
             if p in {"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok",
                      "youtube", "bilibili", "xiaohongshu", "xhs", "wechat", "gzh", "wechat_official",
                      "weixin", "rednote", "zhihu", "juejin"}),
            "",
        )
        brief = platform_rules_brief(platform, 900) if platform else ""
        if platform and not brief:
            raise RuntimeError(f"2026 platform rules unavailable for {platform}; refusing generation without rule context")
        return brief
    except Exception:
        if platform:
            raise
        return ""


def _load_hook_samples(platform: str, max_hooks: int = 5) -> str:
    """加载平台可用钩子模板库作为标题/脚本生成参考（2026-08-16 新增接入）。
    返回浓缩文本注入生成 prompt；失败静默返回空串。
    """
    try:
        from .hooks_loader import pick_hooks

        hooks = pick_hooks(platform, max_hooks)
        if not hooks:
            return ""
        lines = []
        for h in hooks[:max_hooks]:
            template = str(h.get("template") or "")
            example = str(h.get("example") or "")
            lines.append(f"模板: {template}")
            if example:
                lines.append(f"示例: {example}")
        return "\n".join(lines)
    except Exception:
        return ""


def prompt_brief(topic, brief):
    context = build_generation_context(topic, brief)
    return json.dumps(
        {
            "topic": topic,
            "brief": brief,
            "language": context.get("language", "zh"),
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "source_summary": context["source_summary"],
            "topic_clusters": context["topic_clusters"],
            "niche_report": context["niche_report"],
            "viral_score": context["viral_score"],
            "strategy": context["strategy"],
            "historical_feedback": context.get("historical_feedback", {}),
            "cluster_memory": context.get("cluster_memory", []),
            "content_hygiene": context.get("content_hygiene", {}),
            "cornerstone_mode": context.get("cornerstone_mode", False),
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "narration_guide": context.get("narration_guide", ""),
            "platform_rules": context.get("platform_rules", ""),
            "open_notebook_research": context.get("open_notebook_research", {}),
        },
        ensure_ascii=False,
    )
