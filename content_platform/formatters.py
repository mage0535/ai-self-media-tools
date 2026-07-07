import html
import re
import subprocess
import tempfile
from pathlib import Path


def _html_anything(markdown: str) -> str | None:
    """Try html-anything CLI, fall back to simple converter"""
    md_path = None
    out_path = None
    try:
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        tf.write(markdown)
        md_path = tf.name
        tf.close()
        out_path = md_path + ".html"
        r = subprocess.run(
            ["html-anything", "-t", "article", "-o", out_path, md_path],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            html = Path(out_path).read_text(encoding="utf-8")
            start = html.find("<body")
            end = html.find("</body>")
            if start != -1 and end != -1:
                start = html.index(">", start) + 1
                return html[start:end]
            return html
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    finally:
        for p in [md_path, out_path]:
            if p:
                try: Path(p).unlink(missing_ok=True)
                except OSError: pass
    return None


def _plain(text):
    return re.sub(r"[#*_`>]+", "", str(text)).strip()


def _hashtags(job):
    draft_meta = job.get("draft_meta", {})
    if draft_meta.get("hashtags"):
        return ["#" + str(word).lstrip("#").replace(" ", "") for word in draft_meta["hashtags"][:6]]
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}", job.get("topic", ""))
    tags = list(dict.fromkeys(words + ["AI内容", "效率工具"]))[:6]
    return ["#" + word.replace(" ", "") for word in tags]


def _html_article(body):
    sections = []
    for block in str(body).split("\n\n"):
        clean = block.strip()
        if not clean:
            continue
        if clean.startswith("# "):
            sections.append(f"<h1>{html.escape(clean[2:])}</h1>")
        elif clean.startswith("## "):
            sections.append(f"<h2>{html.escape(clean[3:])}</h2>")
        else:
            sections.append(f"<p>{html.escape(_plain(clean)).replace(chr(10), '<br>')}</p>")
    return "".join(sections)


def format_for_platform(job, platform):
    platform = platform.lower()
    title, body = job["title"].strip(), job["body"].strip()
    profile = job.get("profile", "default")
    draft_meta = job.get("draft_meta", {})
    base = {"platform": platform, "sources": job.get("brief", {}).get("sources", []), "profile": profile}
    if platform in {"wechat", "weixin", "wechat_official"}:
        html_body = _html_anything(body) or _html_article(body)
        return {**base, "kind": "article", "title": title[:64], "summary": _plain(body)[:120], "html": html_body}
    if platform in {"xiaohongshu", "rednote"}:
        hook = (draft_meta.get("hook", "") + "\n\n") if draft_meta.get("hook") else ""
        return {**base, "kind": "note", "title": _plain(title)[:20], "text": (hook + _plain(body))[:950], "hashtags": _hashtags(job)}
    if platform in {"youtube"}:
        desc = _plain(body)[:5000]
        return {**base, "kind": "video", "title": title[:100], "caption": desc, "hashtags": _hashtags(job)}
    if platform in {"bilibili"}:
        return {**base, "kind": "article", "title": title[:80], "caption": _plain(body)[:100], "markdown": body, "hashtags": _hashtags(job)}
    if platform in {"douyin", "tiktok", "kuaishou", "shipinhao"}:
        hook = draft_meta.get("hook", "")
        caption = f"{hook} {_plain(body)}".strip() if hook else _plain(body)
        script = draft_meta.get("video_prompt") or _plain(body)
        return {**base, "kind": "video", "title": _plain(title)[:30], "caption": caption[:220], "script": script[:1200], "hashtags": _hashtags(job)}
    if platform in {"twitter", "x", "threads", "mastodon", "bluesky"}:
        text = f"{_plain(title)}\n\n{_plain(body)}"
        limit = 280 if platform in {"twitter", "x"} else 500
        return {**base, "kind": "short", "text": text[:limit]}
    if platform in {"linkedin"}:
        text = f"{title}\n\n{_plain(body)}"[:3000]
        return {**base, "kind": "post", "title": title[:200], "text": text, "hashtags": _hashtags(job)}
    if platform in {"reddit"}:
        return {**base, "kind": "post", "title": title[:300], "text": body[:40000], "subreddit": "auto"}
    if platform in {"facebook", "instagram", "pinterest"}:
        text = _plain(body)[:2000]
        return {**base, "kind": "short", "text": text}
    return {**base, "kind": "article", "title": title, "markdown": body}
