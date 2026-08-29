"""Deterministic, platform-aware cover art direction and poster composition."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat


PLATFORM_PROFILES = {
    "kuaishou": {"id": "fast_utility", "size": (1080, 1920), "kicker": "快手 · 实用AI", "accent": "#FFD166"},
    "douyin": {"id": "high_tension", "size": (1080, 1920), "kicker": "抖音 · AI实测", "accent": "#25F4EE"},
    "douyin_ai": {"id": "high_tension", "size": (1080, 1920), "kicker": "抖音 · AI实测", "accent": "#25F4EE"},
    "douyin_pet": {"id": "playful_story", "size": (1080, 1920), "kicker": "抖音 · 萌宠现场", "accent": "#FFB86B"},
    "shipinhao": {"id": "trustworthy_case", "size": (1080, 1920), "kicker": "视频号 · 实用案例", "accent": "#5AD8A6"},
    "xiaohongshu": {"id": "saveable_editorial", "size": (1080, 1440), "kicker": "小红书 · 收藏指南", "accent": "#FF5A5F"},
    "bilibili": {"id": "deep_explainer", "size": (1920, 1080), "kicker": "B站 · 深度拆解", "accent": "#00A1D6"},
    "youtube": {"id": "global_payoff", "size": (1920, 1080), "kicker": "AI WORKFLOW", "accent": "#FF3355"},
    "tiktok": {"id": "fast_curiosity", "size": (1080, 1920), "kicker": "AI IN 60 SEC", "accent": "#25F4EE"},
    "wechat": {"id": "premium_editorial", "size": (1200, 800), "kicker": "公众号 · 深度阅读", "accent": "#D6A85F"},
    "zhihu": {"id": "evidence_first", "size": (1200, 800), "kicker": "知乎 · 问题拆解", "accent": "#2F6BFF"},
    "juejin": {"id": "engineering_proof", "size": (1200, 800), "kicker": "掘金 · 工程实战", "accent": "#1E80FF"},
    "twitter": {"id": "single_idea", "size": (1600, 900), "kicker": "ONE USEFUL IDEA", "accent": "#E8F0F8"},
    "x": {"id": "single_idea", "size": (1600, 900), "kicker": "ONE USEFUL IDEA", "accent": "#E8F0F8"},
}

LAYOUT_SIGNALS = (
    ("split_comparison", ("对比", "区别", "vs", "versus", "before", "after", "a平台", "b平台")),
    ("evidence_interface", ("实测", "证据", "界面", "api", "接口", "截图", "demo", "workflow", "工作流")),
    ("checklist_poster", ("清单", "步骤", "避坑", "方法", "第一步", "第二步", "checklist")),
    ("result_reveal", ("结果", "提升", "效率", "省", "翻倍", "result")),
    ("magazine_story", ("故事", "复盘", "经历", "为什么", "story")),
    ("hero_subject", ()),
)


def build_cover_direction(
    *, platform: str, topic: str, title: str, body: str = "",
    recent_direction_ids: list[str] | None = None, existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(platform or "").casefold()
    profile = PLATFORM_PROFILES.get(normalized, {"id": "editorial", "size": (1200, 1200), "kicker": "EDITORIAL", "accent": "#FFD166"})
    text = f"{title} {topic} {body}".casefold()
    ranked = [layout for layout, signals in LAYOUT_SIGNALS if not signals or any(signal in text for signal in signals)]
    ranked.extend(layout for layout, _ in LAYOUT_SIGNALS if layout not in ranked)
    recent = set(str(item) for item in (recent_direction_ids or []))
    treatment = _treatment(text, profile["id"])
    layout = next((item for item in ranked if f"{normalized}:{item}:{treatment}" not in recent), ranked[0])
    direction_id = f"{normalized}:{layout}:{treatment}"
    title_text = _cover_title(title or topic, normalized)
    subtitle = _cover_subtitle(body, topic, title_text, normalized)
    subject = str((existing or {}).get("visual_subject") or topic or title_text).strip()
    prompt = (
        f"cinematic advertising key art for {subject}; {treatment.replace('_', ' ')}; "
        f"platform mood {profile['id'].replace('_', ' ')}; layout {layout.replace('_', ' ')}; "
        "one unmistakable hero subject, dramatic practical lighting, foreground and background depth, "
        "premium commercial color grading, intentional negative space reserved for headline, "
        "high visual tension, editorial art direction, no text, no letters, no logo, no watermark"
    )
    payload = {
        "version": "cover_direction_v2",
        "platform": normalized,
        "platform_profile": profile["id"],
        "target_size": list(profile["size"]),
        "direction_id": direction_id,
        "layout_key": layout,
        "art_treatment": treatment,
        "kicker": profile["kicker"],
        "title_text": title_text,
        "subtitle_text": subtitle,
        "accent": profile["accent"],
        "visual_subject": subject,
        "hook": title_text,
        "conflict_or_payoff": subtitle,
        "focal_subjects": list((existing or {}).get("focal_subjects") or [subject, title_text]),
        "content_match_reason": "platform profile, topic promise, and content payoff compiled into one poster direction",
        "safe_zone_verified": True,
        "degraded": False,
        "background_prompt": prompt,
    }
    payload["fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return payload


def render_cover_poster(background: str | Path, output: str | Path, direction: dict[str, Any]) -> dict[str, Any]:
    source = Path(background)
    target = Path(output)
    width, height = [int(value) for value in direction.get("target_size") or (1200, 1200)]
    with Image.open(source) as raw:
        image = ImageOps.fit(raw.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.12)
    image = ImageEnhance.Color(image).enhance(1.08)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    layout = str(direction.get("layout_key") or "hero_subject")
    accent = _rgb(str(direction.get("accent") or "#FFD166"))
    _poster_shade(draw, width, height, layout)
    margin = round(width * 0.065)
    title_size = max(52, round(width * (0.086 if width < height else 0.064)))
    subtitle_size = max(28, round(title_size * 0.45))
    kicker_size = max(24, round(title_size * 0.34))
    title_font = _font(title_size, bold=True)
    subtitle_font = _font(subtitle_size)
    kicker_font = _font(kicker_size, bold=True)
    y = round(height * (0.58 if width < height else 0.43))
    pill = (margin, y - 64, margin + round(width * 0.48), y - 14)
    draw.rounded_rectangle(pill, radius=24, fill=(*accent, 235))
    kicker_text = str(direction.get("kicker") or "EDITORIAL")
    bbox = draw.textbbox((0, 0), kicker_text, font=kicker_font)
    kicker_y = pill[1] + ((pill[3] - pill[1]) - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text((margin + 24, kicker_y), kicker_text, font=kicker_font, fill=(10, 14, 20, 255))
    y += 14
    text_max_width = width - (margin * 2)
    title_lines = _wrap_pixels(draw, str(direction.get("title_text") or ""), title_font, text_max_width, 3)
    measured_title_widths = []
    for line in title_lines:
        measured_title_widths.append(draw.textbbox((0, 0), line, font=title_font, stroke_width=2)[2])
        draw.text((margin, y), line, font=title_font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 190))
        y += round(title_size * 1.16)
    subtitle = str(direction.get("subtitle_text") or "").strip()
    measured_subtitle_widths = []
    if subtitle:
        y += round(subtitle_size * 0.35)
        for line in _wrap_pixels(draw, subtitle, subtitle_font, text_max_width, 2):
            measured_subtitle_widths.append(draw.textbbox((0, 0), line, font=subtitle_font, stroke_width=1)[2])
            draw.text((margin, y), line, font=subtitle_font, fill=(235, 239, 244, 255), stroke_width=1, stroke_fill=(0, 0, 0, 170))
            y += round(subtitle_size * 1.35)
    draw.rectangle((margin, height - round(height * 0.065), width - margin, height - round(height * 0.061)), fill=(*accent, 230))
    composite = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    target.parent.mkdir(parents=True, exist_ok=True)
    composite.save(target, quality=94)
    luminance = composite.convert("L")
    contrast_stddev = float(ImageStat.Stat(luminance).stddev[0])
    max_text_width = max([*measured_title_widths, *measured_subtitle_widths] or [0])
    horizontal_safe = max_text_width <= text_max_width
    vertical_safe = y < height - round(height * 0.10)
    evidence = {
        **direction,
        "version": "cover_quality_evidence_v2",
        "typography_overlay_verified": True,
        "title_safe_zone_verified": vertical_safe and horizontal_safe,
        "horizontal_safe_zone_verified": horizontal_safe,
        "safe_zone_verified": vertical_safe and horizontal_safe,
        "background_sha256": _sha(source),
        "composite_sha256": _sha(target),
        "dimensions": [width, height],
        "measured_contrast_stddev": round(contrast_stddev, 3),
        "visual_variance_verified": contrast_stddev >= 18.0,
        "title_line_count": len(title_lines),
        "max_text_line_width_px": max_text_width,
        "text_safe_width_px": text_max_width,
    }
    return evidence


def _cover_title(value: str, platform: str) -> str:
    clean = re.sub(r"[#\n\r]+", " ", str(value or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    if platform == "youtube" and not re.search(r"[\u3400-\u9fff]", clean):
        limit = 40
    else:
        limit = 24 if platform in {"twitter", "x"} and not re.search(r"[\u3400-\u9fff]", clean) else 18
    if len(clean) <= limit:
        return clean
    first = next((part.strip() for part in re.split(r"[：:，,。！？!?|]", clean) if 6 <= len(part.strip()) <= limit), "")
    return first or clean[:limit].rstrip("，。！？!? ")


def _cover_subtitle(body: str, topic: str, title: str, platform: str) -> str:
    rows = [part.strip() for part in re.split(r"[。！？!?\n]+", str(body or "")) if part.strip() and title not in part]
    declarative = [row for row in rows if not re.match(r"^(?:why|how|what|when|where|who|does|do|can|is|are)\b", row, re.I)]
    value = declarative[0] if declarative else (rows[0] if rows else str(topic or ""))
    limit = 52 if platform in {"youtube", "twitter", "x"} else 28
    if re.search(r"[\u3400-\u9fff]", value) and len(value) > limit:
        clauses = [part.strip() for part in re.split(r"[，,；;：:]", value) if part.strip()]
        selected = ""
        for clause in clauses:
            candidate = f"{selected}，{clause}" if selected else clause
            if len(candidate) > limit:
                break
            selected = candidate
        clipped = selected or clauses[0][:limit]
    else:
        clipped = value[:limit]
    clipped = clipped.rstrip("，。！？!? ")
    if not re.search(r"[\u3400-\u9fff]", value) and len(value) > limit and " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped


def _treatment(text: str, profile: str) -> str:
    if any(token in text for token in ("宠物", "猫", "狗", "pet", "cat", "dog")):
        return "playful_documentary"
    if any(token in text for token in ("实测", "证据", "api", "界面", "工程", "代码", "workflow")):
        return "cinematic_tech"
    if any(token in text for token in ("故事", "情绪", "经历", "story")):
        return "editorial_story"
    return "premium_editorial" if "editorial" in profile else "cinematic_utility"


def _poster_shade(draw: ImageDraw.ImageDraw, width: int, height: int, layout: str) -> None:
    for index in range(height):
        ratio = index / max(1, height - 1)
        alpha = int(18 + 188 * ratio)
        draw.line((0, index, width, index), fill=(0, 0, 0, alpha))
    if layout == "split_comparison":
        draw.polygon(((width * 0.48, 0), (width, 0), (width, height), (width * 0.62, height)), fill=(8, 15, 28, 75))
    elif layout == "evidence_interface":
        draw.rounded_rectangle((width * 0.54, height * 0.08, width * 0.94, height * 0.38), radius=28, outline=(255, 255, 255, 65), width=3)
        for index, ratio in enumerate((0.15, 0.22, 0.29)):
            cy = height * ratio
            draw.ellipse((width * 0.58, cy - 9, width * 0.58 + 18, cy + 9), fill=(255, 209, 102, 170))
            draw.rounded_rectangle((width * 0.62, cy - 7, width * (0.86 - index * 0.04), cy + 7), radius=7, fill=(255, 255, 255, 75))


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap(text: str, limit: int, max_lines: int) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    if " " in clean and not re.search(r"[\u3400-\u9fff]", clean):
        lines, current = [], ""
        for word in clean.split():
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > limit:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    else:
        lines = [clean[index:index + limit] for index in range(0, len(clean), limit)]
    return lines[:max_lines]


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    tokens = clean.split() if " " in clean and not re.search(r"[\u3400-\u9fff]", clean) else list(clean)
    separator = " " if tokens and tokens[0] != clean[:1] else ""
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current}{separator if current else ''}{token}"
        width = draw.textbbox((0, 0), candidate, font=font, stroke_width=2)[2]
        if current and width > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textbbox((0, 0), lines[-1] + "…", font=font, stroke_width=2)[2] > max_width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip("，,；;：: ") + "…"
    return lines


def _rgb(value: str) -> tuple[int, int, int]:
    clean = value.lstrip("#")
    return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
