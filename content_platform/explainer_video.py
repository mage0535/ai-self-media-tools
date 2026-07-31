"""Article-to-explainer-video planning.

This module turns a finished article into a deterministic package that the
existing image and video toolchain can consume. It does not render by itself;
rendering remains guarded by MediaBridge, video_toolchain_runner, Cinema,
Shotcraft, subtitle, BGM, and visual gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .video_toolchain import build_video_toolchain_plan


VISUAL_TYPES = ["title", "problem", "workflow", "comparison", "checklist", "summary"]


def read_article(path: str | Path) -> tuple[str, str]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
    title = ""
    body = text.strip()
    for line in body.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            title = clean.lstrip("#").strip()
            break
    if not title:
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        title = first[:60] or "Knowledge explainer"
    return title, body


def build_explainer_storyboard(
    article: str,
    title: str = "",
    target_pages: int = 8,
    aspect_ratio: str = "16:9",
    presenter_side: str = "right",
) -> dict[str, Any]:
    """Build a PPT-style explainer storyboard from article text."""

    clean_title = (title or _infer_title(article) or "Knowledge explainer").strip()
    pages = max(4, min(12, int(target_pages or 8)))
    beats = _article_beats(article, pages - 2)
    page_rows = [
        _page(
            1,
            "title",
            clean_title,
            _short_payoff(article),
            [clean_title[:18], "结构化讲解", "可发布视频"],
            f"开场先讲清楚这一期要解决的问题：{clean_title}。",
            aspect_ratio,
            presenter_side,
        )
    ]
    for index, beat in enumerate(beats, start=2):
        page_rows.append(
            _page(
                index,
                VISUAL_TYPES[(index - 1) % (len(VISUAL_TYPES) - 1) + 1],
                beat["title"],
                beat["message"],
                beat["keywords"],
                beat["narration"],
                aspect_ratio,
                presenter_side,
            )
        )
    page_rows.append(
        _page(
            len(page_rows) + 1,
            "summary",
            "最后给一个可执行动作",
            "把观点落到今天就能做的一步",
            ["行动", "复盘", "下一步"],
            "结尾不要再堆信息，只给观众一个明确动作，并引导评论或收藏。",
            aspect_ratio,
            presenter_side,
        )
    )
    script = "\n\n".join(f"{row['page']}. {row['title']}\n{row['narration']}" for row in page_rows)
    plan = build_video_toolchain_plan(
        {
            "content_form": "article_explainer_video",
            "primary_platforms": ["youtube", "bilibili", "kuaishou"],
            "asset_plan": ["article", "knowledge_cards", "human_voiceover", "background_music", "content_images"],
        },
        {
            "content_line": "article_to_explainer_video",
            "video_line": "knowledge explainer video with ppt pages and narration",
            "topic": clean_title,
        },
    )
    return {
        "ok": True,
        "title": clean_title,
        "content_form": "article_explainer_video",
        "aspect_ratio": aspect_ratio,
        "presenter_side": presenter_side,
        "pages": page_rows,
        "narration_script": script,
        "video_toolchain_plan": plan,
        "quality_contract": {
            "requires_storyboard": True,
            "requires_section_images": True,
            "requires_voiceover": True,
            "requires_real_instrument_bgm": True,
            "requires_lower_third_subtitles": True,
            "requires_cinema_and_shotcraft_manifest": True,
        },
    }


def write_explainer_package(
    article_path: str | Path,
    output_dir: str | Path,
    title: str = "",
    target_pages: int = 8,
    aspect_ratio: str = "16:9",
    presenter_side: str = "right",
) -> dict[str, Any]:
    inferred_title, article = read_article(article_path)
    package = build_explainer_storyboard(article, title or inferred_title, target_pages, aspect_ratio, presenter_side)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    storyboard_path = out / "explainer_storyboard.json"
    slides_path = out / "slides.md"
    plan_path = out / "video_toolchain_plan.json"
    prompts_path = out / "image_prompts.json"
    storyboard_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    slides_path.write_text(_slides_markdown(package), encoding="utf-8")
    plan_path.write_text(json.dumps(package["video_toolchain_plan"], ensure_ascii=False, indent=2), encoding="utf-8")
    prompts_path.write_text(json.dumps(_image_prompts(package), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "title": package["title"],
        "pages": len(package["pages"]),
        "storyboard": str(storyboard_path),
        "slides": str(slides_path),
        "video_toolchain_plan": str(plan_path),
        "image_prompts": str(prompts_path),
        "selected_pipeline": package["video_toolchain_plan"].get("selected_pipeline", ""),
        "template_family": package["video_toolchain_plan"].get("template_family", ""),
        "required_tools": package["video_toolchain_plan"].get("required_tools", []),
    }


def _infer_title(article: str) -> str:
    for line in article.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:80]
    return ""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n{2,}", text)
    return [re.sub(r"\s+", " ", item).strip(" #\t") for item in parts if len(item.strip()) > 12]


def _article_beats(article: str, count: int) -> list[dict[str, Any]]:
    sentences = _sentences(article)
    if not sentences:
        sentences = [article.strip() or "先把问题讲清楚，再给出方法和行动。"]
    chunk = max(1, len(sentences) // max(1, count))
    beats = []
    for index in range(count):
        seg = sentences[index * chunk : (index + 1) * chunk] or sentences[-chunk:]
        message = " ".join(seg)[:160]
        keywords = _keywords(message)
        beats.append(
            {
                "title": _beat_title(message, index),
                "message": message,
                "keywords": keywords,
                "narration": _narration(message, keywords),
            }
        )
    return beats


def _beat_title(text: str, index: int) -> str:
    title = re.sub(r"[。！？!?；;].*$", "", text).strip()
    title = title[:28] if title else f"关键点 {index + 1}"
    return title


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,6}", text)
    seen = []
    for token in tokens:
        if token not in seen and token not in {"这个", "不是", "然后", "因为", "所以", "如果"}:
            seen.append(token)
        if len(seen) >= 4:
            break
    return seen or ["问题", "方法", "结果"]


def _narration(message: str, keywords: list[str]) -> str:
    return f"这一页重点看 {'、'.join(keywords[:3])}。{message}"


def _short_payoff(article: str) -> str:
    sentences = _sentences(article)
    return (sentences[0] if sentences else article.strip())[:120]


def _page(index: int, visual_type: str, title: str, message: str, keywords: list[str], narration: str, aspect_ratio: str, presenter_side: str) -> dict[str, Any]:
    return {
        "page": index,
        "visual_type": visual_type,
        "title": title,
        "message": message,
        "keywords": keywords[:4],
        "narration": narration,
        "layout": {
            "aspect_ratio": aspect_ratio,
            "presenter_side": presenter_side,
            "page_style": "ppt_explainer",
            "visual_density": "medium",
        },
        "image_prompt": (
            f"PPT-style knowledge explainer illustration for '{title}'. "
            f"Show {message[:90]}. Clean educational composition, clear hierarchy, "
            "real workspace or conceptual diagram, no watermark, minimal readable text."
        ),
    }


def _slides_markdown(package: dict[str, Any]) -> str:
    lines = [f"# {package['title']}", ""]
    for row in package["pages"]:
        lines.extend(
            [
                f"## {row['page']}. {row['title']}",
                "",
                row["message"],
                "",
                "关键词：" + " / ".join(row["keywords"]),
                "",
                "口播：" + row["narration"],
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _image_prompts(package: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "page": row["page"],
            "role": "cover" if row["page"] == 1 else "section",
            "section": row["title"],
            "purpose": "explain adjacent narration in the video page",
            "prompt": row["image_prompt"],
        }
        for row in package["pages"]
    ]
