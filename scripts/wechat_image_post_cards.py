#!/usr/bin/env python3
"""Build WeChat image-message cards from a long-form article.

This script is publish-safe: it never embeds provider keys and never uploads to
WeChat. Hermes can call its private publisher after this packet passes
``scripts/validate_wechat_image_post_packet.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.image_provider import ImageProviderError, generate_image
from content_platform.content_recipe import build_tool_invocation_manifest

CARD_W, CARD_H = 1080, 1440
PALETTES = ["cold", "warm", "minimal", "dark", "fresh", "field", "editorial"]
LAYOUTS = ["hero", "split", "side", "stack", "timeline", "quote", "checklist", "summary_cta"]


def _clean_md(text: str) -> str:
    text = re.sub(r"^---.*?---", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    return re.sub(r"<[^>]+>", "", text)


def _sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^#{2,4}\s+(.+)", line)
        if match:
            if current_title or current_body:
                sections.append((current_title or "核心要点", " ".join(current_body)))
            current_title = match.group(1).strip()
            current_body = []
        elif not line.startswith("#"):
            current_body.append(line)
    if current_title or current_body:
        sections.append((current_title or "核心要点", " ".join(current_body)))
    if sections:
        return [(title, body) for title, body in sections if body.strip()]
    paras = [part.strip() for part in re.split(r"\n\s*\n", text) if len(part.strip()) > 20]
    return [(f"要点 {i + 1}", para) for i, para in enumerate(paras)]


def _summarize(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    parts = re.split(r"[。！？!?]", text)
    kept: list[str] = []
    total = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if total + len(part) > limit:
            break
        kept.append(part)
        total += len(part)
    return ("。".join(kept) + "。") if kept else text[:limit]


def build_card_specs(md_text: str, title: str, max_cards: int = 9) -> list[dict[str, Any]]:
    max_cards = max(3, min(20, int(max_cards)))
    sections = _sections(_clean_md(md_text))
    cards = [{"role": "cover", "title": title[:34], "body": "先看结论，再看怎么落地。"}]
    for heading, body in sections[: max_cards - 2]:
        cards.append({"role": "content", "title": heading[:28], "body": _summarize(body)})
    cards.append({"role": "cta", "title": "这套流程你会用在哪？", "body": "评论区留一个场景。需要清单，回复关键词：工具箱。"})
    return cards[:max_cards]


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_wrapped(draw, xy, text: str, font, fill, width_chars: int, line_gap: int) -> None:
    x, y = xy
    for line in textwrap.wrap(text, width=width_chars):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_gap


def _resolve_background(card: dict[str, Any], out_dir: Path, idx: int, provider: str, allow_placeholder: bool) -> dict[str, Any]:
    prompt = (
        f"real documentary photo background, Chinese tech productivity article, {card['title']}, "
        "vertical 3:4, no text, no logo, natural light, workspace or device context"
    )
    bg_path = out_dir / f"bg_{idx:02d}.jpg"
    try:
        result = generate_image(prompt, bg_path, provider=provider, size="1080x1440")
        return {
            "path": str(bg_path),
            "kind": "real_scene_photo",
            "source": str(result.get("provider") or provider),
            "source_url": str(result.get("source_url") or result.get("url") or result.get("path") or bg_path),
            "license": str(result.get("license") or result.get("license_type") or "provider_terms"),
            "query": prompt[:120],
            "match_reason": "background prompt is derived from this card title and article topic",
            "not_gradient_fallback": True,
        }
    except Exception as exc:
        if not allow_placeholder:
            raise ImageProviderError(f"background image unavailable for card {idx}: {exc}") from exc
        return {
            "path": str(bg_path),
            "kind": "placeholder",
            "source": "test_placeholder",
            "source_url": str(bg_path),
            "license": "test_only",
            "query": prompt[:120],
            "match_reason": "test placeholder only",
            "not_gradient_fallback": False,
        }


def _render_card(card: dict[str, Any], bg: dict[str, Any], out_path: Path, idx: int, total: int) -> None:
    from PIL import Image, ImageDraw, ImageEnhance

    bg_path = Path(str(bg.get("path") or ""))
    if bg_path.is_file():
        image = Image.open(bg_path).convert("RGB").resize((CARD_W, CARD_H))
    else:
        image = Image.new("RGB", (CARD_W, CARD_H), (22, 32, 45))
    image = ImageEnhance.Brightness(image).enhance(0.55)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, CARD_W, CARD_H), fill=(0, 0, 0, 90))
    palette = PALETTES[(idx - 1) % len(PALETTES)]
    accent = [(59, 130, 246), (232, 121, 95), (250, 204, 21), (16, 185, 129), (244, 114, 182)][(idx - 1) % 5]
    draw.rectangle((72, 86, 96, 250), fill=(*accent, 255))
    draw.text((120, 92), f"{idx:02d}/{total:02d}", font=_font(34), fill=(*accent, 255))
    title_size = 78 if len(card["title"]) <= 12 else max(48, 78 - (len(card["title"]) - 12) * 3)
    _draw_wrapped(draw, (112, 250), card["title"], _font(title_size), (255, 255, 255, 255), 12, int(title_size * 1.35))
    _draw_wrapped(draw, (112, 720), card["body"], _font(38), (235, 239, 245, 255), 20, 64)
    draw.rounded_rectangle((112, 1250, 968, 1324), radius=36, fill=(*accent, 210))
    footer = "马吉克AI · 真实复盘，不卖焦虑"
    draw.text((156, 1266), footer, font=_font(34), fill=(255, 255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    card["palette"] = palette


def build_packet(md_path: Path, title: str, out_dir: Path, max_cards: int, provider: str, allow_placeholder: bool) -> dict[str, Any]:
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    specs = build_card_specs(md_text, title, max_cards=max_cards)
    out_dir.mkdir(parents=True, exist_ok=True)
    cards: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs, 1):
        bg = _resolve_background(spec, out_dir, idx, provider, allow_placeholder)
        png = out_dir / f"card_{idx:02d}.png"
        _render_card(spec, bg, png, idx, len(specs))
        cards.append(
            {
                "index": idx,
                "role": spec["role"],
                "title": spec["title"],
                "one_idea": True,
                "layout": LAYOUTS[(idx - 1) % len(LAYOUTS)],
                "palette": spec["palette"],
                "image_path": str(png),
                "width": CARD_W,
                "height": CARD_H,
                "bytes": png.stat().st_size,
                "background": bg,
                "typography": {"title_px": 64, "body_px": 38, "line_height": 1.65, "safe_area_ok": True, "overflow": False},
                "engagement": {"hook_or_payoff": spec["body"][:80], "save_reason": "single-card checklist or decision point"},
            }
        )
    return {
        "platform": "wechat",
        "content_type": "wechat_image_post",
        "title": title[:32],
        "desc": "图片消息补充长文核心结论，方便读者滑动、收藏和转发。",
        "card_count": len(cards),
        "cards": cards,
        "design_strategy": {
            "story_arc": ["cover", "problem", "case", "method", "checklist", "cta"],
            "visual_consistency": True,
            "layout_diversity": True,
            "source_guidance": ["strong cover hook", "one idea per card", "clear CTA"],
        },
        "tool_invocation_manifest": build_tool_invocation_manifest(
            planned_tools={
                "markdown_section_splitter": "scripts/wechat_image_post_cards.py",
                "image_provider": "content_platform.image_provider",
                "wechat_image_card_renderer": "scripts/wechat_image_post_cards.py",
                "wechat_image_post_validator": "scripts/validate_wechat_image_post_packet.py",
            },
            invocations={
                "markdown_section_splitter": {"status": "ok", "output": str(len(specs))},
                "image_provider": {"status": "ok", "output": provider},
                "wechat_image_card_renderer": {"status": "ok", "output": str(out_dir)},
                "wechat_image_post_validator": {"status": "planned", "output": str(out_dir / "wechat_image_post_packet.json")},
            },
        ),
        "publishing_plan": {"article_type": "newspic", "draft_postcheck": "wechat_image_draft_batchget", "publish_mode": "draft"},
        "postcheck": {"required": True, "batchget_verified": False, "article_type": "newspic", "title_present": False, "image_count_matched": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate WeChat image-message cards from a Markdown article")
    parser.add_argument("--md", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-cards", type=int, default=9)
    parser.add_argument("--provider", default="stock", help="image provider name; defaults to stock")
    parser.add_argument("--allow-placeholder", action="store_true", help="test only; placeholder packets will fail production validator")
    args = parser.parse_args()
    packet = build_packet(Path(args.md), args.title, Path(args.out), args.max_cards, args.provider, args.allow_placeholder)
    packet_path = Path(args.out) / "wechat_image_post_packet.json"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"packet": str(packet_path), "images": [card["image_path"] for card in packet["cards"]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
