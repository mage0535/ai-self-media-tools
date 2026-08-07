"""Zhihu pin promotion — after an article is drafted, build a companion pin
(想法) that teases the article and drives engagement.

Design: keep it simple. `build_pin_text()` is pure text generation (no side
effects); `publish_article_pin()` posts it via the zhihu CLI adapter. The
caller decides whether to publish directly or hand the text to a human for
review — domestic platforms default to review-first.
"""
import re

from .zhihu_cli_adapter import ZhihuCliAdapter


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_md_title(text: str) -> str:
    """Remove leading markdown heading lines (# Title) from a body."""
    lines = str(text or "").splitlines()
    while lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    return "\n".join(lines)


def build_pin_text(job: dict, article_url: str = "", extra: str = "") -> dict:
    """Generate a companion pin (想法) payload from an article job.

    Returns {"title": ..., "content": ...}. Title is the article headline
    (short form for the pin's bold header); content teases the article and
    invites engagement.
    """
    title = _clean(job.get("title") or "")
    body = _clean(_strip_md_title(job.get("body") or ""))
    hook = ""
    if body:
        # first ~120 chars of the article body often carry the opening hook;
        # cut at a sentence boundary if one is nearby to avoid mid-sentence truncation
        hook = _sentence_clip(body, 120)
    lines = []
    if hook:
        lines.append(hook)
    if title:
        lines.append(f"完整拆解在专栏文章《{title}》里，看完你也能照着做。")
    elif article_url:
        lines.append("完整拆解在专栏文章里，看完你也能照着做。")
    if article_url:
        lines.append(article_url)
    if extra:
        lines.append(_clean(extra))
    content = "\n".join(lines)
    return {"title": title, "content": content}


def _sentence_clip(text: str, max_chars: int) -> str:
    """Clip text to max_chars, preferring to break at a Chinese sentence end."""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    for sep in ("。", "！", "？", "；"):
        idx = head.rfind(sep)
        if idx >= max_chars * 0.5:
            return head[: idx + 1]
    return head + "…"


def publish_article_pin(job: dict, article_url: str = "", extra: str = "",
                        images: list | None = None, timeout: int = 60) -> dict:
    """Publish a companion pin for an article via the zhihu CLI adapter.

    Returns the CLI result dict {id, url, raw}. Raises ZhihuCliError on
    failure. Caller must ensure the article is already published (a pin
    pointing to a not-yet-visible draft is pointless).
    """
    payload = build_pin_text(job, article_url=article_url, extra=extra)
    adapter = ZhihuCliAdapter(timeout=timeout)
    return adapter.publish_pin(payload["title"], content=payload["content"], images=images)
